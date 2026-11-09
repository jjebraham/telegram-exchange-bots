from contextlib import closing
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

if sys.platform == 'win32':
    sys.modules.setdefault('fcntl', types.ModuleType('fcntl'))
usage = types.ModuleType('instagram_reel_usage')
usage.tracked = lambda *args, **kwargs: lambda function: function
sys.modules.setdefault('instagram_reel_usage', usage)
import instagram_trial_reels as trial

TEST_DIR = Path(__file__).resolve().parent
ROOT = TEST_DIR.parent if TEST_DIR.name == 'voice_review' else TEST_DIR


def load_tool(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'deploy/instagram-trial-reels' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load_tool('schedule_installer_test', 'activate_trial_reels.py')
audit = load_tool('schedule_audit_test', 'check_reel_schedule.py')


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.state = self.home / '.local/state/kiani-instagram-trial-reels'
        self.db = self.state / 'trial_reels.sqlite3'
        self.patches = [patch.object(trial, 'STATE', self.state), patch.object(trial, 'DB', self.db)]
        for p in self.patches:
            p.start()
        with closing(trial._connect()):
            pass

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def add(self, con, identity, *, origin='daily_top_story', mode='trial', status='container_processing', published_at=None):
        now = time.time()
        con.execute('''INSERT INTO trial_reels(trial_id,source_key,source_url,kind,title_original,title_fa,
            summary_fa,source_name,article_published_at,posted_day,origin,status,caption,created_at,updated_at,
            reel_mode,container_id,media_id,published_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (identity, identity, 'https://example.com/' + identity, 'crypto', 'Saved news', 'خبر آزمایشی',
             'خلاصه خبر آزمایشی.', 'Example', now - 60, trial.istanbul_day(now), origin, status,
             'caption', now, now, mode, 'container-' + identity,
             'media-' + identity if published_at else None, published_at))
        con.commit()

    def test_all_seven_slots_are_trial_and_start_window_is_unchanged(self):
        self.assertEqual(trial.AUTO_SLOTS, ('11:00','12:00','13:00','15:00','17:00','18:00','20:30'))
        self.assertEqual((trial.MAX_PER_DAY, trial.DIRECT_AUTO_PER_DAY, trial.DIRECT_AUTO_SLOTS), (7, 0, ()))
        for slot in trial.AUTO_SLOTS:
            hour, minute = map(int, slot.split(':'))
            due = datetime(2026, 11, 9, hour, minute, tzinfo=trial.ZONE)
            self.assertTrue(trial._slot_due(due, slot))
            self.assertFalse(trial._slot_due(due - timedelta(seconds=1), slot))
            self.assertFalse(trial._slot_due(due + timedelta(minutes=10), slot))

    def test_legacy_direct_entry_point_can_only_dispatch_trials(self):
        with patch.object(trial, '_run_scheduled', return_value='job') as run:
            for slot in ('12:00', '18:00'):
                self.assertEqual(trial.run_direct_daily(self.home, self.home, slot), 'job')
                self.assertEqual(run.call_args.args[-1], 'trial')
            with self.assertRaises(trial.TrialReelError):
                trial.run_direct_daily(self.home, self.home, '15:00')

    def test_automatic_direct_creation_is_rejected_before_any_paid_work(self):
        with patch.object(trial, '_live_guard') as guard, patch.object(trial, '_select_narrator') as voice:
            with self.assertRaises(trial.TrialReelError):
                trial.create_reel({}, 'crypto', origin='daily_direct', reel_mode='direct', asset_root=self.home, scheduled_slot='12:00')
            with self.assertRaises(trial.TrialReelError):
                trial._run_scheduled(self.home, self.home, '12:00', 'direct')
            guard.assert_not_called()
            voice.assert_not_called()

    def test_seventh_trial_is_allowed_but_eighth_is_not_and_manual_limit_is_separate(self):
        with closing(trial._connect()) as con:
            for index in range(6):
                self.add(con, str(index))
            for index in range(5):
                self.add(con, 'admin' + str(index), origin='admin_link')
            trial._enforce_daily_limit(con, 'daily_top_story', trial.istanbul_day())
            self.add(con, 'seventh')
            with self.assertRaises(trial.TrialReelError):
                trial._enforce_daily_limit(con, 'daily_top_story', trial.istanbul_day())
            with self.assertRaises(trial.TrialReelError):
                trial._enforce_daily_limit(con, 'admin_link', trial.istanbul_day())
            trial._enforce_daily_limit(con, 'admin_direct', trial.istanbul_day(), 'direct')

    def test_existing_direct_slot_is_never_replayed_as_trial(self):
        day = trial.istanbul_day()
        with closing(trial._connect()) as con:
            con.execute("INSERT INTO scheduled_runs VALUES (?,?,'published',?,?,NULL,?)", (day, '12:00', time.time(), time.time(), 'already-posted'))
            con.commit()
            self.assertFalse(trial._reserve_auto_slot(con, day, '12:00', time.time()))
            self.assertEqual(con.execute('SELECT status,trial_id FROM scheduled_runs').fetchone()[:], ('published', 'already-posted'))

    def test_trial_container_contract_and_explicit_manual_direct_are_preserved(self):
        fields = trial.container_fields('https://example.com/video.mp4', 'caption', 'trial')
        self.assertEqual(fields['share_to_feed'], 'false')
        self.assertEqual(json.loads(fields['trial_params']), {'graduation_strategy': 'SS_PERFORMANCE'})
        direct = trial.container_fields('https://example.com/video.mp4', 'caption', 'direct')
        self.assertEqual(direct['share_to_feed'], 'true')
        self.assertNotIn('trial_params', direct)

    def test_pending_automatic_direct_jobs_are_held_without_rewriting_history(self):
        with closing(trial._connect()) as con:
            for status in ('rendering','creating_container','container_processing','publishing'):
                self.add(con, status, origin='daily_direct', mode='direct', status=status)
            self.add(con, 'published', origin='daily_direct', mode='direct', status='published', published_at=time.time())
            self.add(con, 'manual', origin='admin_direct', mode='direct')
            self.add(con, 'trial')
            results = trial.hold_legacy_scheduled_direct(con)
            self.assertEqual(len(results), 4)
            for result in results:
                row = con.execute('SELECT status,error_type,reel_mode,container_id FROM trial_reels WHERE trial_id=?', (result['trial_id'],)).fetchone()
                self.assertEqual(tuple(row), ('needs_review', 'ScheduledDirectDisabled', 'direct', 'container-' + result['trial_id']))
            self.assertEqual(con.execute("SELECT status FROM trial_reels WHERE trial_id='published'").fetchone()[0], 'published')
            self.assertEqual(con.execute("SELECT status FROM trial_reels WHERE trial_id='manual'").fetchone()[0], 'container_processing')
            self.assertEqual(trial.hold_legacy_scheduled_direct(con), [])

    def test_poller_does_not_request_or_publish_a_legacy_direct_container(self):
        with closing(trial._connect()) as con:
            self.add(con, 'pending-old', origin='daily_direct', mode='direct')
        ig = types.ModuleType('instagram_daily_rates')
        ig._graph_request, ig._publish_container = Mock(), Mock()
        batch = types.ModuleType('instagram_news_batch')
        batch.guard = Mock()
        retention = types.ModuleType('instagram_direct_reel_retention')
        retention.process_due = Mock()
        with closing(trial._connect()) as active_con, \
                patch.object(trial, '_connect', return_value=active_con), \
                patch.dict(sys.modules, {'instagram_daily_rates': ig, 'instagram_news_batch': batch,
                                        'instagram_direct_reel_retention': retention}), \
                patch.object(trial, '_reconcile_published_voice_history'):
            result = trial.poll_pending(publisher_root=self.home)
        self.assertEqual(result[0]['status'], 'needs_review')
        ig._graph_request.assert_not_called()
        ig._publish_container.assert_not_called()
        batch.guard.assert_not_called()

    def test_launcher_routes_every_slot_to_trial_and_preserves_unrelated_cron(self):
        script = installer.trial_tick_script('#!/bin/bash\n', self.home / 'run-kiani-instagram-trial-reels.sh', self.home / 'trial.log', trial.AUTO_SLOTS)
        self.assertIn('|'.join(trial.AUTO_SLOTS) + ') exec ', script)
        self.assertNotIn('direct-reels', script)
        original = b'5 7 * * * /home/example/another-post.sh\n'
        commands = ['* * * * * /home/example/run-kiani-instagram-reel-schedule.sh']
        changed = installer.replace_trial_cron(original, commands)
        self.assertTrue(changed.startswith(original))
        self.assertEqual(installer.replace_trial_cron(changed, commands), changed)

    def test_installer_refuses_an_old_inflight_direct_render_before_switch(self):
        with closing(trial._connect()) as con:
            self.add(con, 'inflight', origin='daily_direct', mode='direct', status='rendering')
        mkdir = lambda path: path.mkdir(parents=True, exist_ok=True)
        with patch.object(installer, 'private_directory', side_effect=mkdir), \
                patch.object(installer.os, 'getuid', return_value=self.home.stat().st_uid, create=True), \
                patch.object(installer.fcntl, 'LOCK_EX', 2, create=True), \
                patch.object(installer.fcntl, 'LOCK_NB', 4, create=True), \
                patch.object(installer.fcntl, 'flock', create=True):
            with self.assertRaisesRegex(RuntimeError, 'still in progress'):
                with installer.schedule_workers_idle(self.home):
                    self.fail('Must not switch an active direct render')

    def test_installer_can_switch_waiting_containers_and_releases_both_locks(self):
        with closing(trial._connect()) as con:
            self.add(con, 'waiting', origin='daily_direct', mode='direct')
        mkdir = lambda path: path.mkdir(parents=True, exist_ok=True)
        with patch.object(installer, 'private_directory', side_effect=mkdir), \
                patch.object(installer.os, 'getuid', return_value=self.home.stat().st_uid, create=True), \
                patch.object(installer.fcntl, 'LOCK_EX', 2, create=True), \
                patch.object(installer.fcntl, 'LOCK_NB', 4, create=True), \
                patch.object(installer.fcntl, 'flock', create=True) as lock:
            with installer.schedule_workers_idle(self.home):
                handles = [call.args[0] for call in lock.call_args_list]
                self.assertEqual(len(handles), 2)
                self.assertTrue(all(not handle.closed for handle in handles))
            self.assertTrue(all(handle.closed for handle in handles))
        with closing(trial._connect()) as con:
            self.assertEqual(con.execute("SELECT status FROM trial_reels WHERE trial_id='waiting'").fetchone()[0], 'container_processing')

    def test_audit_identifies_failed_missing_and_published_direct_slots_read_only(self):
        revision = 'a' * 40
        config = self.home / '.config/kiani-instagram-manual-news/config.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'installed_revision': revision}))
        source = self.home / '.local/state/kiani-instagram-manual-news/source' / revision
        source.mkdir(parents=True)
        (source / 'instagram_trial_reels.py').write_text('\n'.join(
            key + ' = ' + repr(getattr(trial, key)) for key in ('AUTO_SLOTS','DIRECT_AUTO_SLOTS','MAX_PER_DAY','DIRECT_AUTO_PER_DAY')))
        (self.home / 'run-kiani-instagram-reel-schedule.sh').write_text(installer.trial_tick_script(
            '#!/bin/bash\n', self.home / 'run-kiani-instagram-trial-reels.sh', self.home / 'trial.log', trial.AUTO_SLOTS))
        now = datetime(2026, 11, 9, 13, 46, tzinfo=trial.ZONE)
        day = now.date().isoformat()
        with closing(trial._connect()) as con:
            self.add(con, 'already-direct', origin='daily_direct', mode='direct', status='published', published_at=now.timestamp()-6000)
            con.execute("INSERT INTO scheduled_runs VALUES (?,?,'failed',?,?,?,NULL)", (day, '11:00', now.timestamp(), now.timestamp(), 'NewsError'))
            con.execute("INSERT INTO scheduled_runs VALUES (?,?,'published',?,?,NULL,?)", (day, '12:00', now.timestamp(), now.timestamp(), 'already-direct'))
            con.commit()
        before = self.db.read_bytes()
        result = audit.report(self.home, now)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(result['configured_policy']['MAX_PER_DAY'], 7)
        self.assertEqual(result['installed_routes'][0]['launcher_mode'], 'trial')
        by_slot = {r['slot']: r for r in result['today_slots']}
        self.assertEqual(by_slot['11:00']['error_type'], 'NewsError')
        self.assertEqual(by_slot['12:00']['reel_mode'], 'direct')
        self.assertEqual(by_slot['13:00']['status'], 'not_recorded')
        self.assertEqual(by_slot['15:00']['status'], 'upcoming')
        self.assertEqual(result['successful_publications'][0]['scheduled_direct'], 1)


if __name__ == '__main__':
    unittest.main()

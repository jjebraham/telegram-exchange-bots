from datetime import datetime, timezone
from pathlib import Path
import json, os, sqlite3, tempfile, unittest
from unittest.mock import patch
import runpod_reel_render as render


class RenderTests(unittest.TestCase):
    def test_monthly_budget_reserves_maximum_session_and_never_rolls_into_next_month(self):
        con=sqlite3.connect(':memory:')
        now=datetime(2026,11,10,tzinfo=timezone.utc)
        self.assertEqual(render.spend_guard(con,now),'2026-11')
        con.execute('INSERT INTO render_spend VALUES(?,?,?,?,?)',('other-page','2026-11','lease',9.6,'CLOSED'))
        with self.assertRaises(render.RenderError) as caught: render.spend_guard(con,now)
        self.assertTrue(caught.exception.fallback_safe)
        self.assertEqual(render.spend_guard(con,datetime(2026,12,1,tzinfo=timezone.utc)),'2026-12')

    def test_bundle_transfers_only_explicit_inputs_and_preserves_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runtime=root/'source'; assets=root/'assets'
            for base,names in ((runtime,('instagram_trial_reels.py','instagram_reel_motion.py','instagram_reel_usage.py',
                                        'voice_review/reel_audio_mix.py','voice_review/runpod_remote_render.py','voice_review/runpod_native_guard.py',
                                        'credentials.env','production.sqlite3')),
                               (assets,('fonts/Vazirmatn-Regular.ttf','fonts/Vazirmatn-Bold.ttf','assets/instagram/kiani-logo.svg'))):
                for name in names:
                    p=base/name; p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
            photo=root/'photo.jpg';photo.write_bytes(b'image')
            audio=root/'audio.wav';audio.write_bytes(b'audio')
            story={'title_fa':'عنوان خبر','summary_fa':'خلاصه خبر.','source_name':'source','secret':'never-transfer'}
            with patch.dict(os.environ,{'REEL_MUSIC_VOLUME':'0.20'}):
                data=render.bundle(story,'economy',assets,[{'path':photo}],
                    [{'path':audio,'duration':1.5,'word_starts':[0,.5],'spoken_script':'private extra'}],None,root/'job',runtime=runtime)
            self.assertNotIn('secret',data['story'])
            self.assertNotIn('spoken_script',data['narration'][0])
            self.assertEqual(data['narration'][0]['word_starts'],[0,.5])
            self.assertFalse(any('credentials' in p or 'sqlite' in p for p in data['manifest']))
            self.assertTrue((root/'job/bundle.tgz').is_file())

    def test_unsafe_symlink_input_is_rejected_before_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runtime=root/'source';runtime.mkdir()
            target=root/'target';target.write_text('x')
            try: (runtime/'instagram_trial_reels.py').symlink_to(target)
            except OSError: self.skipTest('symlinks unavailable')
            with self.assertRaises(render.RenderError) as caught:
                render.bundle({},'crypto',root,[],None,None,root/'job',runtime=runtime)
            self.assertTrue(caught.exception.fallback_safe)

    def test_encoder_is_explicit_and_local_preset_is_unchanged(self):
        import instagram_reel_motion as motion
        self.assertEqual(motion.encoder_arguments('libx264'),['-c:v','libx264','-preset','veryfast','-crf','25'])
        self.assertIn('h264_nvenc',motion.encoder_arguments('h264_nvenc'))
        with self.assertRaises(ValueError): motion.encoder_arguments('injected; command')

    def test_cleanup_removes_only_job_copies_and_retains_metadata_and_source_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'job';root.mkdir(mode=0o700)
            original=Path(tmp)/'original.wav';original.write_bytes(b'original')
            directory=root/'narration';directory.mkdir();(directory/'0.wav').write_bytes(original.read_bytes())
            (root/'session.json').write_text('{}');(root/'output.mp4').write_bytes(b'video')
            render.cleanup_inputs(root)
            self.assertEqual(original.read_bytes(),b'original')
            self.assertTrue((root/'session.json').is_file());self.assertFalse(directory.exists());self.assertFalse((root/'output.mp4').exists())


if __name__=='__main__': unittest.main()

#!/usr/bin/env python3
"""Read the active schedule and saved results without importing publisher code."""
import ast
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, time as clock_time
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo


def report(home, now=None):
    zone = ZoneInfo('Europe/Istanbul')
    now = datetime.now(zone) if now is None else now.astimezone(zone)
    config = json.loads((home / '.config/kiani-instagram-manual-news/config.json').read_text())
    revision = config['installed_revision']
    if not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('Invalid active revision')
    runtime = home / '.local/state/kiani-instagram-manual-news/source' / revision
    wanted = {'AUTO_SLOTS', 'DIRECT_AUTO_SLOTS', 'MAX_PER_DAY', 'DIRECT_AUTO_PER_DAY'}
    constants = {}
    for node in ast.parse((runtime / 'instagram_trial_reels.py').read_bytes()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    constants[target.id] = ast.literal_eval(node.value)
    slots = sorted(set(constants.get('AUTO_SLOTS', ())) | set(constants.get('DIRECT_AUTO_SLOTS', ())))
    routes = []
    launcher = home / 'run-kiani-instagram-reel-schedule.sh'
    if launcher.is_file() and not launcher.is_symlink():
        for line in launcher.read_text().splitlines():
            match = re.match(r'\s*((?:\d{2}:\d{2})(?:\|\d{2}:\d{2})*)\)\s+exec\s+', line)
            if match:
                mode = ('direct' if 'run-kiani-instagram-direct-reels.sh' in line else
                        'trial' if 'run-kiani-instagram-trial-reels.sh' in line else 'unknown')
                routes.append({'slots': match.group(1).split('|'), 'launcher_mode': mode})
    result = {'checked_istanbul': now.isoformat(timespec='seconds'), 'active_revision': revision,
              'configured_policy': constants, 'installed_routes': routes,
              'today_slots': [], 'successful_publications': [], 'translation_attempts': []}
    path = home / '.local/state/kiani-instagram-trial-reels/trial_reels.sqlite3'
    if not path.is_file() or path.is_symlink():
        result['database'] = 'unavailable'
        return result
    day = now.date().isoformat()
    start = datetime.combine(now.date() - timedelta(days=6), clock_time.min, tzinfo=zone).timestamp()
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute('''SELECT s.slot,s.status,s.error_type,s.trial_id,
            r.reel_mode,r.origin,r.media_id,r.error_type AS reel_error
            FROM scheduled_runs s LEFT JOIN trial_reels r ON r.trial_id=s.trial_id
            WHERE s.posted_day=? ORDER BY s.slot''', (day,)).fetchall()
        saved = {row['slot']: dict(row) for row in rows}
        for slot in sorted(set(slots) | set(saved)):
            hour, minute = map(int, slot.split(':'))
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            item = saved.get(slot, {'slot': slot, 'status': 'not_recorded' if now >= due else 'upcoming'})
            result['today_slots'].append(item)
        counts = Counter()
        for row in con.execute('''SELECT published_at,reel_mode,origin FROM trial_reels
            WHERE status='published' AND published_at>=?''', (start,)):
            published_day = datetime.fromtimestamp(row['published_at'], zone).date().isoformat()
            category = 'scheduled' if row['origin'] in {'daily_top_story', 'daily_direct'} else 'manual'
            counts[published_day, category, row['reel_mode']] += 1
        for offset in range(7):
            date = (now.date() - timedelta(days=offset)).isoformat()
            result['successful_publications'].append({'day': date,
                'scheduled_trial': counts[date, 'scheduled', 'trial'],
                'scheduled_direct': counts[date, 'scheduled', 'direct'],
                'manual_trial': counts[date, 'manual', 'trial'],
                'manual_direct': counts[date, 'manual', 'direct']})
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'scheduled_translation_attempts' in tables:
            for row in con.execute('''SELECT slot,position,kind,source_url,status,error_code,unsupported_json
                FROM scheduled_translation_attempts WHERE posted_day=? ORDER BY slot,position''', (day,)):
                item = dict(row)
                try:
                    item['unsupported_numbers'] = json.loads(item.pop('unsupported_json'))
                except (ValueError, TypeError):
                    item['unsupported_numbers'] = 'unreadable_saved_diagnostic'
                result['translation_attempts'].append(item)
    return result


if __name__ == '__main__':
    data = report(Path.home())
    for key in ('checked_istanbul','active_revision','configured_policy','installed_routes'):
        print(key + ':', json.dumps(data[key], ensure_ascii=False))
    print('\nTODAY SLOTS (saved mode is the original publication mode)')
    for row in data['today_slots']:
        print(json.dumps(row, ensure_ascii=False))
    print('\nRECORDED SUCCESSFUL PUBLICATIONS')
    for row in data['successful_publications']:
        print(json.dumps(row, ensure_ascii=False))
    print('\nTODAY TRANSLATION ATTEMPTS (new diagnostic records only)')
    for row in data['translation_attempts']:
        print(json.dumps(row, ensure_ascii=False))
    print('Read-only check complete; no service contacted or publication changed.')

#!/usr/bin/env python3
"""Add early, same-anchor retries to the installed weekly comparison."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

REVISION = '4745d848a1253b5c3ec39bf86a723b4c560ff8cd'
FILES = ('weekly_market_data.py','instagram_weekly_markets.py','instagram_weekly_markets_renderer.py',
         'iran_gold_data.py','iran_gold_quorum.py','iran_gold_servix.py','economic_calendar_data.py',
         'instagram_economic_calendar_renderer.py','assets/instagram/gold-coin.png','assets/instagram/gold-bars.png')


def revised_cron(raw, home):
    launcher = str(home / 'publish-kiani-instagram-weekly-markets.sh')
    old = f'30,35,40 16 * * * {launcher} >> {home}/kiani-instagram-weekly-markets-cron.log 2>&1'
    new = old.replace('30,35,40 16 ', '30,31,32,35,40 16 ', 1)
    lines = raw.decode('utf-8').splitlines(keepends=True)
    zones, matches = {}, []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        match = re.fullmatch(r'''(CRON_TZ|TZ)\s*=\s*(["']?)([^"'\s]+)\2''', stripped)
        if match:
            zones[match.group(1)] = match.group(3)
            continue
        malformed = re.match(r'^(CRON_TZ|TZ)\s*=', stripped)
        if malformed:
            zones[malformed.group(1)] = 'UNREVIEWED'
            continue
        if launcher in line:
            if any(value not in {'UTC', 'Etc/UTC'} for value in zones.values()):
                raise RuntimeError('Weekly cron timezone requires review.')
            if stripped not in {old, new}:
                raise RuntimeError('Weekly cron entry differs from reviewed schedule.')
            matches.append(i)
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one weekly cron entry.')
    i = matches[0]
    lines[i] = lines[i].replace(old, new, 1)
    return ''.join(lines).encode()


def read_owned(path):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
        raise RuntimeError('Unexpected file type or ownership: ' + path.name)
    return path.read_bytes()


def cron():
    return subprocess.check_output(['crontab', '-l'], timeout=15)


def self_test():
    from pathlib import PurePosixPath
    home = PurePosixPath('/home/example')
    old = b'30,35,40 16 * * * /home/example/publish-kiani-instagram-weekly-markets.sh >> /home/example/kiani-instagram-weekly-markets-cron.log 2>&1\n'
    new = old.replace(b'30,35,40 16 ', b'30,31,32,35,40 16 ', 1)
    tail = b'CRON_TZ=Europe/Istanbul\n* * * * * /home/example/other.sh\n'
    assert revised_cron(old + tail, home) == new + tail
    assert revised_cron(new + tail, home) == new + tail
    for bad in (b'CRON_TZ=Europe/Istanbul\n' + old, old + old):
        try: revised_cron(bad, home)
        except RuntimeError: pass
        else: raise AssertionError('Unsafe cron accepted')
    print('Cron scope, early retries, unchanged entries and idempotence: passed.')


def main():
    import fcntl
    home = Path.home()
    state = home / '.local/state/kiani-instagram-weekly-markets'
    activation = json.loads(read_owned(state/'activation.json'))
    if activation.get('revision') != REVISION:
        raise RuntimeError('Installed weekly revision differs.')
    if datetime.now(ZoneInfo('Asia/Tehran')).utcoffset() != timedelta(hours=3, minutes=30):
        raise RuntimeError('Tehran timezone changed.')
    zone = subprocess.check_output(['timedatectl','show','--property=Timezone','--value'], timeout=10).decode().strip()
    if zone not in {'UTC','Etc/UTC'} or subprocess.run(['systemctl','is-active','--quiet','cron'], timeout=10).returncode:
        raise RuntimeError('Expected an active UTC cron service.')
    release = home/'kiani-instagram-weekly-markets-releases'/REVISION
    digest = hashlib.sha256(b'\0'.join(n.encode()+b'\0'+read_owned(release/n) for n in FILES)).hexdigest()
    if digest != activation.get('runtime_hash'):
        raise RuntimeError('Installed weekly runtime fingerprint differs.')
    launcher = read_owned(home/'publish-kiani-instagram-weekly-markets.sh')
    expected = str(release/'instagram_weekly_markets.py').encode()
    if launcher.count(expected) != 1 or b'--scheduled' not in launcher:
        raise RuntimeError('Installed weekly launcher differs.')
    lock_path = state/'publication.lock'
    fd = os.open(lock_path, os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0), 0o600)
    with os.fdopen(fd,'r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before = cron()
        after = revised_cron(before, home)
        if after == before:
            print('Early retries are already installed; no change made.')
            return
        backup = Path(tempfile.mkdtemp(prefix='kiani-weekly-retries-backup-',dir=home))
        os.chmod(backup,0o700)
        path = backup/'crontab.txt'
        path.write_bytes(before); path.chmod(0o600)
        if cron() != before:
            raise RuntimeError('Crontab changed during verification; retry.')
        subprocess.run(['crontab','-'],input=after,capture_output=True,check=True,timeout=15)
        if cron() != after:
            raise RuntimeError('Installed crontab changed concurrently; review the backup.')
    print('Installed daily 20:00, 20:01, 20:02 Tehran observation attempts; existing 20:05 and 20:10 retries retained.')
    print('Backup:',path)
    print('Existing source, timestamp and publishing rules preserved; no price or Instagram request made.')


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--self-test']: self_test()
    elif len(sys.argv) == 1:
        try: main()
        except Exception as exc:
            print('Weekly retry repair stopped:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__)
            raise SystemExit(1)
    else: raise SystemExit('Use no arguments to install or --self-test to check.')


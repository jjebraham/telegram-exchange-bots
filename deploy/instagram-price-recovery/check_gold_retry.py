"""Verify the scheduled retry decision without external requests."""
import ast
from datetime import datetime, time, timedelta, timezone
from pathlib import Path, PurePosixPath
import re

source = Path(__file__).resolve().parents[2] / 'instagram_iran_gold.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'defer_for_global_retry')
zone = timezone(timedelta(hours=3, minutes=30))
namespace = {'wall_time': time, 'TEHRAN': zone}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
defer = namespace['defer_for_global_retry']
start = datetime(2026, 10, 31, 10, 0, tzinfo=zone)
at = lambda minute: start.replace(minute=minute)
assert defer(True, 'verified', 'blocked', start, at(0))
assert defer(True, 'verified', 'blocked', start, at(5))
assert not defer(True, 'verified', 'blocked', start, at(10))
assert not defer(True, 'verified', 'verified', start, at(0))
assert not defer(False, 'verified', 'blocked', start, at(0))
assert not defer(True, 'blocked', 'blocked', start, at(0))
print('10:00 and 10:05 defer; 10:10 falls back; verified metals publish immediately.')
activation = Path(__file__).with_name('activate_recovery.py')
tree = ast.parse(activation.read_text(encoding='utf-8'))
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'revised_cron')
cron_scope = {'re': re}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(activation), 'exec'), cron_scope)
revised = cron_scope['revised_cron']
home = PurePosixPath('/home/example')
job = b'30,35,40 6 * * * /home/example/publish-kiani-instagram-iran-gold.sh\n'
later = b'CRON_TZ=Europe/Istanbul\n* * * * * /home/example/other.sh\n'
assert revised(job + later, home, 'gold') == job + later
assert revised(b'CRON_TZ=UTC\n' + job + later, home, 'gold') == b'CRON_TZ=UTC\n' + job + later
legacy = job.replace(b'30,35,40 6 ', b'30 6 ', 1)
assert revised(legacy + later, home, 'gold') == job + later
reset = b'CRON_TZ=Europe/Istanbul\nCRON_TZ=UTC\n'
assert revised(reset + legacy + later, home, 'gold') == reset + job + later
for prefix in (b'CRON_TZ=Europe/Istanbul\n', b'CRON_TZ=bad zone\n'):
    try:
        revised(prefix + job, home, 'gold')
    except RuntimeError:
        pass
    else:
        raise AssertionError('Custom or malformed timezone before gold job was accepted.')
try:
    revised(job + job, home, 'gold')
except RuntimeError:
    pass
else:
    raise AssertionError('Duplicate gold cron jobs were accepted.')
print('Cron timezone scope verified; unrelated later entries are preserved.')
print('No price, DeepSeek, Telegram or Instagram request was made.')

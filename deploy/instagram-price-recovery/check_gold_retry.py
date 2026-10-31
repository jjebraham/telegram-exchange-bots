"""Verify the scheduled retry decision without external requests."""
import ast
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

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
print('No price, DeepSeek, Telegram or Instagram request was made.')

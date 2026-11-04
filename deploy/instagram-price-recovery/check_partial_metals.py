#!/usr/bin/env python3
"""Privately replay the saved silver disagreement without live price requests."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--audit', type=Path, default=(Path.home()/'.local/state/kiani-instagram-iran-gold/runs/20261104-101003-bd98ad46/audit.json'))
args = parser.parse_args()
sys.path.insert(0, str(args.runtime.resolve()))
import global_metals_data as metals
import instagram_global_metals_renderer as renderer
from iran_gold_data import stamp

data = json.loads(args.audit.read_text())
old = data['snapshot']['global_metals']
moment = stamp(old['generated_at'])
try:
    metals.assess(old['providers'], moment)
except metals.GoldError:
    pass
else:
    raise RuntimeError('The saved full board unexpectedly verifies; use a disagreement audit.')
gold = metals.assess(old['providers'], moment, gold_only=True)
board = dict(old, status='gold_only', rows=gold, ratio=None)
metals.validate(board, now=moment)
assert 'نرخ نقره تأیید نشد' in renderer.caption(board)
assets = Path.home()/'kiani-instagram-publisher'
with tempfile.TemporaryDirectory(prefix='kiani-gold-partial-') as folder:
    paths = renderer.render(board, folder, assets, preview=True)
    if len(paths) != 1 or not Path(paths[0]).is_file():
        raise RuntimeError('The gold-only preview was not created.')
print('Saved disagreement: gold corroborated; silver and ratio withheld.')
print('Private gold-only global slide rendered; no Meta or price request made.')


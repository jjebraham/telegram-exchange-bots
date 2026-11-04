#!/usr/bin/env python3
"""Check previous evidence and a live Servix pair without publication."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', required=True, type=Path)
args = parser.parse_args()
sys.path.insert(0, str(args.runtime.resolve()))
import weekly_market_data as data
from iran_gold_servix import load_key

db = Path.home()/'.local/state/kiani-instagram-weekly-markets/markets.sqlite3'
with sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True) as con:
    row = con.execute('SELECT snapshot_json FROM observations ORDER BY anchor DESC LIMIT 1').fetchone()
if not row:
    raise RuntimeError('A previous verified weekly observation is required for compatibility testing.')
snapshot = json.loads(row[0])
data.validate(snapshot)
print('Existing verified observation remains valid:', snapshot.get('anchor'), flush=True)
key = load_key()
raw = {'servix_catalog': data.fetch(data.CATALOG, key),
       'servix_prices': data.fetch(data.CURRENT, key)}
quotes, _, retried = data.consistent_servix_pair(raw, key, datetime.now(timezone.utc))
if set(quotes) != set(data.CODES):
    raise RuntimeError('A complete set of verified Servix instruments is required.')
print('Fresh Servix pair verified:', len(quotes), 'instruments; retried:', retried, flush=True)
print('No Meta or DeepSeek request made; no historical observations changed.')


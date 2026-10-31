#!/usr/bin/env python3
"""Offline lock-retry preflight and read-only news history check."""
import argparse
from contextlib import contextmanager
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', required=True, type=Path)
args = parser.parse_args()
runtime = args.runtime.resolve()
sys.path[:0] = [str(runtime), str(runtime/'selector_trial_runtime')]
import instagram_trial_reels as reels
import instagram_ranked_news as ranked
from instagram_crypto_news import NewsError

elapsed = [0]
attempts = []
@contextmanager
def busy_then_free(kind):
    attempts.append(kind)
    if len(attempts) == 1:
        raise NewsError('A news selection/publisher is already running; retry after it finishes.')
    yield

def advance(seconds):
    elapsed[0] += seconds

with reels.wait_for_scheduled_news_lock(
        busy_then_free, 30, sleeper=advance, clock=lambda: elapsed[0]):
    pass
if len(attempts) != 2 or elapsed[0] != 15:
    raise RuntimeError('Scheduled lock retry verification failed.')
print('Busy news lock: retried and acquired without publication.')

try:
    blocked, history = ranked.histories(time.time())
    print('Read-only news history: accessible;',
          len(blocked), 'blocked URLs and', len(history), 'recent/unresolved entries.')
except NewsError as exc:
    message = str(exc)
    if 'http' in message.lower() or len(message) > 200:
        message = 'News history validation failed.'
    print('Read-only news history stopped:', message)
    raise SystemExit(1)
print('No Meta, Telegram or DeepSeek request was made.')

"""Bound hourly news by a ten-per-category daily cap and live Story quota."""
from __future__ import annotations

import json
from pathlib import Path
import time

from instagram_insights_data import Graph, InsightsError, STATE, inventory, read_db, story_config

PER_SLOT = 1
PER_DAY = 10
CORE_RESERVE = 12  # Six Feed/Story pairs cover daily non-news + overlapping weekly calendars.


def activation():
    path = STATE / 'activation.json'
    if path.is_symlink() or not path.is_file():
        raise InsightsError('News batch policy has not been activated.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('news_batch_enabled') is not True:
        raise InsightsError('News batch policy has not been activated.')
    schedule = data.get('news_schedule', {})
    if schedule.get('per_slot') != 1 or schedule.get('per_category_day') != PER_DAY or schedule.get('timezone') != 'Europe/Istanbul':
        raise InsightsError('The corrected hourly news schedule has not been activated.')
    return data


def plan(publishing):
    if not publishing:
        return PER_DAY, dict(mode='preview', requested_per_slot=PER_SLOT, requested_per_category_day=PER_DAY)
    graph = Graph()
    config = activation()
    if config.get('account_id') != graph.account_id:
        raise InsightsError('News batch policy belongs to another account.')
    quota = graph.publishing_quota()
    if graph.pressure:
        raise InsightsError('Meta usage pressure requires deferring extra news.')
    # Two categories, each requiring both a Feed and a Story. Do not assume
    # quota_total=100, or assume deleting a post refunds any publishing quota.
    cap = min(PER_DAY, max(0, (quota['total'] - CORE_RESERVE) // (2 * 2)))
    return cap, dict(quota, requested_per_slot=PER_SLOT, requested_per_category_day=PER_DAY, fair_per_category_day_cap=cap,
                     core_reserve=CORE_RESERVE, feed_story_cost=2)


def guard():
    graph, config = Graph(), story_config()
    activated = activation()
    if activated.get('account_id') != graph.account_id:
        raise InsightsError('News batch account differs.')
    quota = graph.publishing_quota()
    if graph.pressure:
        raise InsightsError('Meta usage pressure requires deferring extra news.')
    con = read_db(config['db'])
    try:
        rows = con.execute('SELECT feed_id,status FROM stories WHERE discovered_at>=?', (time.time() - 7 * 3600,)).fetchall()
    finally:
        con.close()
    known = {row['feed_id']: row['status'] for row in rows}
    pending = {key for key, status in known.items() if status in {'discovered', 'queued', 'processing', 'publishing', 'needs_review'}}
    published, health = inventory(config, time.time() - 7 * 3600)
    if any(value != 'ok' for value in health.values()):
        raise InsightsError('Cannot verify pending Story reservations; defer this news post.')
    pending.update(key for key in published if key not in known)
    required = CORE_RESERVE + len(pending) + 2
    if quota['remaining'] < required:
        raise InsightsError('Publishing quota is reserved for existing posts/Stories; defer extra news.')
    return dict(quota, pending_stories=len(pending), reserved_units=required)


def event_groups(con, engine, eligible, history, audit, checkpoint):
    """Compare every historical report in bounded chunks, without dropping dedup."""
    ids = [row['id'] for row in eligible]
    parents = {key: key for key in ids}
    matches, reasons = {}, {}

    def root(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    batches = [history[i:i + 80] for i in range(0, len(history), 80)] or [[]]
    audit['grouping_diagnostics']['history_batches'] = []
    for batch in batches:
        diagnostic = {}
        groups = engine.event_groups(con, eligible, batch, diagnostics=diagnostic)
        # engine.event_groups already verifies exact candidate coverage, ID
        # namespaces and historical matches. Merge conservatively across chunks.
        for group in groups:
            members = group['members']
            for key in members[1:]:
                parents[root(key)] = root(members[0])
            for key in members:
                if group['published_match']:
                    matches[key] = group['published_match']
                reasons.setdefault(key, group['reason'])
        audit['grouping_diagnostics']['history_batches'].append(dict(history_ids=[row['id'] for row in batch], diagnostics=diagnostic))
        if checkpoint:
            checkpoint(audit)
    merged = {}
    for key in ids:
        merged.setdefault(root(key), []).append(key)
    return [dict(members=sorted(members), published_match=next((matches[key] for key in members if key in matches), None),
                 reason='; '.join(sorted({reasons[key] for key in members})))
            for members in merged.values()]

"""Independent public-endpoint polling with bounded backoff and immediate publishing."""
from concurrent.futures import ThreadPoolExecutor
import json
import random
import time


def serve(collector, snapshot_path, save, selectors):
    replies, errors, pending = {}, {}, {}
    due = {selector: 0.0 for selector in selectors}
    failures = {selector: 0 for selector in selectors}
    published = 0.0
    last_status = None
    with ThreadPoolExecutor(max_workers=10) as pool:
        while True:
            changed = False
            for selector, future in list(pending.items()):
                if not future.done():
                    continue
                del pending[selector]
                changed = True
                try:
                    response = future.result()
                    replies[selector] = response
                    errors.pop(selector, None)
                    failures[selector] = 0
                    due[selector] = time.monotonic() + 8 + random.uniform(0, 1)
                except Exception as exc:
                    failures[selector] += 1
                    errors[selector] = f'{type(exc).__name__}: {str(exc)[:220]}'
                    replies.pop(selector, None)
                    # Bound concurrent work and avoid repeated bursts at a failing API.
                    delay = min(60, 4 * 2 ** min(failures[selector] - 1, 4))
                    due[selector] = time.monotonic() + delay + random.uniform(0, 2)
            now = time.monotonic()
            if changed or now - published >= 2:
                snapshot = collector.collect(replies=replies, errors=errors)
                snapshot['collection_policy'] = 'independent-endpoints-v1'
                snapshot['collector_health'] = {
                    'in_flight': len(pending), 'failing_endpoints': len(errors),
                    'last_updated_utc': snapshot['generated_at_utc'],
                }
                save(snapshot_path, snapshot, public=True)
                published = now
                status = (snapshot['source_count'], snapshot['ok'], tuple(sorted(errors)))
                if status != last_status:
                    print(json.dumps({'source_count': snapshot['source_count'],
                        'quorum': snapshot['ok'], 'failing_endpoints': len(errors),
                        'policy': 'independent-endpoints-v1'}), flush=True)
                    last_status = status
            for selector in selectors:
                if selector not in pending and now >= due[selector]:
                    pending[selector] = pool.submit(collector.transport.fetch, selector)
            time.sleep(0.25)

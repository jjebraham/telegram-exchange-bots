"""Watchdog decision core for a future managed Runpod session.

This module has no CLI or installed timer. Integration must provide a verified
independent timer, trusted worker-lock state, explicit exclusive Pod ownership,
and protected credentials. Until then it is exercised only with a fake API.
"""
import time

from runpod_api_client import ActionOutcomeUnknown, RunpodAPIError
from runpod_guard import GuardError, Limits, watchdog_decision
import runpod_lease_store as leases
from runpod_worker_lock import pod_lock


def tick(con, api, lease_id, *, expected_pod_id, exclusive, worker_lock_held, worker_active,
         output_pending, job_done, limits=Limits(), now=None):
    """Inspect one lease and conservatively stop its confirmed Pod if safe."""
    # The integration must hold an actual shared worker lock for this entire
    # call. A boolean alone is not evidence of an OS lock.
    if exclusive is not True or worker_lock_held is not True:
        return 'manual_review'
    if any(not isinstance(v, bool) for v in (worker_active, output_pending, job_done)):
        raise GuardError('Watchdog inputs must be explicit booleans')
    row = con.execute('SELECT * FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
    if row is None or row['pod_id'] != expected_pod_id:
        return 'manual_review'
    if row['state'] == 'CLOSED':
        return 'closed'
    now = time.time() if now is None else now
    if not isinstance(now, (int, float)) or now < row['created_at']:
        return 'manual_review'
    if worker_active:
        return 'wait'
    if output_pending:
        return 'manual_review'
    if row['state'] == 'RESERVED':
        # Under the shared lock, a RESERVED lease cannot yet have sent start.
        try:
            leases.cancel_unused_reservation(con, lease_id)
            return 'closed'
        except leases.LeaseError:
            return 'busy'
    start_pending = (row['state'] == 'START_REQUESTED' or
                     row['state'] == 'ACTION_UNCERTAIN' and row['uncertain_from'] == 'START_REQUESTED')
    stop_pending = (row['state'] == 'STOP_REQUESTED' or
                    row['state'] == 'ACTION_UNCERTAIN' and row['uncertain_from'] == 'STOP_REQUESTED')
    if not start_pending and not stop_pending and row['state'] != 'START_CONFIRMED':
        return 'manual_review'
    try:
        pod = api.status(expected_pod_id)
    except RunpodAPIError:
        return 'status_unavailable'
    if not isinstance(pod, dict) or pod.get('id') != expected_pod_id:
        return 'manual_review'
    if start_pending:
        if pod.get('status') != 'RUNNING':
            # Never close an ambiguous start just because the Pod is stopped:
            # the original request might still arrive later.
            return 'wait' if now - row['created_at'] < limits.max_uptime_seconds else 'manual_review'
        try:
            leases.start_confirmed(con, lease_id, pod_id=expected_pod_id, provider_status='RUNNING',
                                   provider_started_at=pod.get('startedAt'),
                                   max_start_delay_seconds=limits.max_uptime_seconds)
            row = con.execute('SELECT * FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
        except leases.LeaseError:
            return 'manual_review'
    if pod.get('status') == 'EXITED':
        try:
            if row['state'] == 'START_CONFIRMED':
                leases.stop_requested(con, lease_id)
            leases.close_confirmed(con, lease_id, pod_id=expected_pod_id, provider_status='EXITED')
            return 'closed'
        except leases.LeaseError:
            return 'busy'
    # Never stop a later externally restarted Pod or retry an uncertain stop.
    if (pod.get('status') != 'RUNNING' or pod.get('startedAt') != row['provider_started_at'] or
            stop_pending):
        return 'manual_review'
    decision = watchdog_decision(owned=True, ownership_certain=True, worker_active=False,
                                 job_done=job_done, output_pending=False,
                                 lease_expired=now - row['created_at'] >= limits.max_uptime_seconds)
    if decision != 'stop_owned_pod':
        return decision
    if not isinstance(pod.get('actions'), list) or 'stop' not in pod['actions'] or pod.get('locked') is not False:
        return 'manual_review'
    try:
        # The atomic state transition ensures only one concurrent tick can send.
        leases.stop_requested(con, lease_id)
    except leases.LeaseError:
        return 'busy'
    try:
        updated = api.transition(expected_pod_id, 'stop')
    except (ActionOutcomeUnknown, RunpodAPIError):
        leases.action_uncertain(con, lease_id)
        return 'action_uncertain'
    if not isinstance(updated, dict) or updated.get('id') != expected_pod_id:
        leases.action_uncertain(con, lease_id)
        return 'action_uncertain'
    if updated.get('status') == 'EXITED':
        leases.close_confirmed(con, lease_id, pod_id=expected_pod_id, provider_status='EXITED')
        return 'closed'
    return 'stop_requested'


def locked_tick(con, api, lease_id, *, state_dir, expected_pod_id, exclusive,
                output_pending, job_done, limits=Limits(), now=None):
    """Hold the Pod lock during the complete check and possible transition."""
    with pod_lock(state_dir, expected_pod_id) as held:
        if not held:
            return 'lock_busy'
        return tick(con, api, lease_id, expected_pod_id=expected_pod_id, exclusive=exclusive,
                    worker_lock_held=True, worker_active=False, output_pending=output_pending,
                    job_done=job_done, limits=limits, now=now)

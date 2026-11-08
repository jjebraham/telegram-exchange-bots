"""Opt-in Runpod lifecycle coordinator; not wired to live publishing.

The production adapter must independently verify the timer, subprocess time
limit, bootstrap, SSH host key, and exclusive job ownership. This module has no
CLI or installation side effects and is currently tested only with fake APIs.
"""
import re
import time

from runpod_api_client import ActionOutcomeUnknown
from runpod_guard import GuardError, Limits, may_start
import runpod_lease_store as leases
import runpod_watchdog
from runpod_worker_lock import pod_lock


class ManagerError(RuntimeError):
    pass


def render_target(pod):
    """Return only connection metadata; never pass provider env to the Pod."""
    ssh = pod.get('ssh') if isinstance(pod.get('ssh'), dict) else {}
    direct = ssh.get('direct') if isinstance(ssh.get('direct'), dict) else {}
    host, port, username = direct.get('host'), direct.get('port'), direct.get('username')
    if (not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9.:-]{1,253}', host) or
            isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535 or
            not isinstance(username, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,31}', username)):
        raise ManagerError('Direct SSH connection details were not verified.')
    return {'pod_id': pod['id'], 'ssh_host': host, 'ssh_port': port, 'ssh_user': username}


def run_job(con, api, *, state_dir, pod_id, enabled=False, exclusive=False,
            watchdog_ready=False, bootstrap_ready=False, identity_ready=False,
            runtime_limit_verified=False, budget_remaining=0, work=None, verify=None,
            limits=Limits(), wait=time.sleep, monotonic=time.monotonic):
    """Start one managed job, verify output on Selenium, and request shutdown.

    Callers must hold a real OS lock via this function and must separately
    arrange an independent watchdog. ``work`` is responsible for bounded,
    supervised remote work; ``verify`` must validate the retrieved artifact.
    An ambiguous provider response is never retried or treated as a success.
    """
    if enabled is not True or runtime_limit_verified is not True:
        raise ManagerError('Managed Runpod execution is disabled or not supervised.')
    if not callable(work) or not callable(verify):
        raise ManagerError('A bounded work function and local output verifier are required.')
    with pod_lock(state_dir, pod_id) as held:
        if not held:
            raise ManagerError('Another worker holds the Pod lock.')
        pod = api.status(pod_id)
        try:
            plan = may_start(pod, pod_id, limits, exclusive=exclusive,
                             watchdog_ready=watchdog_ready, bootstrap_ready=bootstrap_ready,
                             identity_ready=identity_ready, worker_lock_held=True,
                             budget_remaining=budget_remaining)
        except GuardError as exc:
            raise ManagerError(str(exc)) from None
        lease = leases.reserve(con, pod_id, plan['hourly_rate'])
        # No remote work exists yet; the worker must protect outputs before it
        # invokes any remote operation that can create them.
        leases.set_output_pending(con, lease, pending=False)
        leases.start_requested(con, lease)
        try:
            try:
                pod = api.transition(pod_id, 'start')
            except ActionOutcomeUnknown:
                leases.action_uncertain(con, lease)
                raise ManagerError('Pod start outcome is uncertain and needs reconciliation.') from None
            deadline = monotonic() + limits.startup_timeout_seconds
            while pod.get('status') in ('PROVISIONING', 'STARTING'):
                if monotonic() >= deadline:
                    leases.action_uncertain(con, lease)
                    raise ManagerError('Pod startup timed out and needs reconciliation.')
                wait(min(5, max(.01, deadline - monotonic())))
                pod = api.status(pod_id)
            if pod.get('id') != pod_id or pod.get('status') != 'RUNNING':
                leases.action_uncertain(con, lease)
                raise ManagerError('A running Pod could not be verified; reconciliation is required.')
            try:
                leases.start_confirmed(con, lease, pod_id=pod_id, provider_status='RUNNING',
                                       provider_started_at=pod.get('startedAt'),
                                       max_start_delay_seconds=limits.max_uptime_seconds)
            except leases.LeaseError:
                leases.action_uncertain(con, lease)
                raise ManagerError('Pod generation was not verified; reconciliation is required.') from None
            target = render_target(pod)
            # From this point a renderer might leave required output remotely.
            leases.set_output_pending(con, lease, pending=True)
            output = work(target, lease)
            if verify(output) is not True:
                raise ManagerError('Retrieved output was not verified; manual recovery is required.')
            leases.set_output_pending(con, lease, pending=False)
            return output
        finally:
            row = con.execute('SELECT state,output_pending FROM leases WHERE lease_id=?', (lease,)).fetchone()
            if row and row['state'] == 'START_REQUESTED':
                # A transport failure during polling can leave a start in flight.
                leases.action_uncertain(con, lease)
            elif row and row['state'] == 'START_CONFIRMED':
                outcome = runpod_watchdog.tick(
                    con, api, lease, expected_pod_id=pod_id, exclusive=exclusive,
                    worker_lock_held=True, worker_active=False,
                    output_pending=row['output_pending'] != 0, job_done=True, limits=limits)
                if outcome != 'closed':
                    raise ManagerError('Pod shutdown or output recovery needs review: ' + outcome)

"""Disabled-by-default independent watchdog runner.

No timer is installed by this module. The live integration must hold the same
Pod lock from before lease creation until the managed worker has exited, and
must persist output state before and after remote rendering.
"""
import re

from runpod_guard import Limits
import runpod_watchdog


class SupervisorError(ValueError):
    pass


def parse_config(data):
    if not isinstance(data, dict):
        raise SupervisorError('Invalid Runpod settings.')
    enabled = data.get('enabled', False)
    exclusive = data.get('exclusive_during_managed_job', False)
    pod_id = data.get('pod_id')
    if not isinstance(enabled, bool) or not isinstance(exclusive, bool):
        raise SupervisorError('Runpod flags must be explicit booleans.')
    if not isinstance(pod_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', pod_id):
        raise SupervisorError('Invalid Runpod Pod ID.')
    if enabled and not exclusive:
        raise SupervisorError('Exclusive ownership must be explicitly configured.')
    limits = Limits(max_hourly_usd=data.get('max_hourly_usd', 1.0),
                    max_uptime_seconds=data.get('max_uptime_seconds', 1800),
                    startup_timeout_seconds=data.get('startup_timeout_seconds', 300),
                    job_timeout_seconds=data.get('job_timeout_seconds', 900),
                    idle_timeout_seconds=data.get('idle_timeout_seconds', 120))
    return {'enabled': enabled, 'exclusive': exclusive, 'pod_id': pod_id, 'limits': limits}


def run_once(con, api, *, state_dir, config, now=None):
    """Inspect at most one managed lease; never adopt an unrelated Pod."""
    cfg = parse_config(config)
    if not cfg['enabled']:
        return 'disabled'
    row = con.execute('''SELECT lease_id, state, output_pending FROM leases WHERE pod_id=?
        AND state IN ('RESERVED','START_REQUESTED','START_CONFIRMED','ACTION_UNCERTAIN','STOP_REQUESTED')''',
                      (cfg['pod_id'],)).fetchone()
    if row is None:
        return 'idle'
    # Unknown/legacy state always protects outputs and prevents shutdown.
    pending = row['output_pending'] != 0
    return runpod_watchdog.locked_tick(
        con, api, row['lease_id'], state_dir=state_dir, expected_pod_id=cfg['pod_id'],
        exclusive=cfg['exclusive'], output_pending=pending, job_done=True,
        limits=cfg['limits'], now=now)

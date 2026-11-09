"""Offline safety decisions for a future opt-in Runpod lifecycle manager.

This module does not send requests, create Pods, stop Pods, or start a watchdog.
All decisions are fail-closed and must be rechecked against live state under an
exclusive lock immediately before an eventual control action.
"""
from dataclasses import dataclass
import math


class GuardError(ValueError):
    pass


def _number(value, name, *, minimum=0, maximum=1000000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise GuardError(name + ' is invalid')
    if not minimum <= value <= maximum:
        raise GuardError(name + ' is outside the supported range')
    return float(value)


@dataclass(frozen=True)
class Limits:
    max_hourly_usd: float = 1.0
    max_uptime_seconds: int = 1800
    startup_timeout_seconds: int = 300
    job_timeout_seconds: int = 900
    idle_timeout_seconds: int = 120

    def __post_init__(self):
        _number(self.max_hourly_usd, 'hourly limit', minimum=.01, maximum=1000)
        for name in ('max_uptime_seconds', 'startup_timeout_seconds', 'job_timeout_seconds', 'idle_timeout_seconds'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 86400:
                raise GuardError(name + ' is invalid')
        if self.startup_timeout_seconds > self.max_uptime_seconds or self.job_timeout_seconds > self.max_uptime_seconds:
            raise GuardError('timeouts cannot exceed maximum uptime')


def estimated_compute_cost(rate, seconds):
    rate = _number(rate, 'hourly rate', maximum=1000)
    seconds = _number(seconds, 'runtime', maximum=31 * 86400)
    return rate * seconds / 3600


def may_start(pod, expected_id, limits, *, exclusive, watchdog_ready, bootstrap_ready,
              identity_ready, worker_lock_held, budget_remaining, purpose='render'):
    """Validate startup prerequisites; this function never starts a Pod."""
    if not isinstance(pod, dict) or not isinstance(expected_id, str) or not expected_id:
        raise GuardError('Pod identity is missing')
    if pod.get('id') != expected_id:
        raise GuardError('Pod identity does not match')
    if purpose not in ('render', 'api_probe'):
        raise GuardError('Unsupported managed purpose')
    checks = [(exclusive, 'exclusive ownership'), (watchdog_ready, 'watchdog'),
              (worker_lock_held, 'worker lock')]
    if purpose == 'render':
        checks.extend(((bootstrap_ready, 'bootstrap'), (identity_ready, 'SSH identity')))
    for value, name in checks:
        if value is not True:
            raise GuardError(name + ' is not verified')
    if pod.get('status') != 'EXITED' or pod.get('locked') is not False:
        raise GuardError('Pod is not confirmed stopped and unlocked')
    if not isinstance(pod.get('actions'), list) or 'start' not in pod['actions']:
        raise GuardError('Runpod does not currently permit start')
    gpu = pod.get('gpu')
    if not isinstance(gpu, dict) or isinstance(gpu.get('count'), bool) or not isinstance(gpu.get('count'), int) or gpu['count'] < 1:
        raise GuardError('GPU configuration is unavailable')
    rate = _number(pod.get('cost'), 'hourly rate', minimum=.000001, maximum=1000)
    if rate > limits.max_hourly_usd:
        raise GuardError('Pod hourly rate exceeds the configured cap')
    reserve = estimated_compute_cost(rate, limits.max_uptime_seconds)
    if _number(budget_remaining, 'remaining budget', maximum=1000000) < reserve:
        raise GuardError('Insufficient budget for the maximum allowed uptime')
    return {'hourly_rate': rate, 'maximum_uptime_seconds': limits.max_uptime_seconds,
            'reserved_compute_usd': reserve}


def watchdog_decision(*, owned, ownership_certain, worker_active, job_done,
                      output_pending, lease_expired):
    """Return a decision, never perform it; uncertain ownership is escalated."""
    if any(not isinstance(value, bool) for value in
           (owned, ownership_certain, worker_active, job_done, output_pending, lease_expired)):
        raise GuardError('Watchdog inputs must be explicit booleans')
    if not owned or not ownership_certain:
        return 'manual_review'
    if worker_active:
        return 'wait'
    if output_pending:
        return 'manual_review'
    if job_done or lease_expired:
        return 'stop_owned_pod'
    return 'wait'

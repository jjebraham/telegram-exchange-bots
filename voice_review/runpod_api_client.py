"""Minimal Runpod v2 API transport for the future, disabled-by-default manager.

No actions run at import time. A caller must enforce ownership, locking,
price limits and a verified independent watchdog before invoking a transition.
Responses and credentials must never be logged: API responses may contain env.
"""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RunpodAPIError(RuntimeError):
    pass


class ActionOutcomeUnknown(RunpodAPIError):
    """The provider may have processed the request; never blindly retry it."""
    def __init__(self, message, *, http_status=None):
        super().__init__(message)
        self.http_status = http_status if isinstance(http_status, int) and 100 <= http_status <= 599 else None


class ActionRejected(RunpodAPIError):
    """An explicit client-error response refused a start; no automatic retry."""
    def __init__(self, *, http_status, category):
        super().__init__('Runpod start rejected: ' + category)
        self.http_status, self.category = http_status, category


def rejected_start(error):
    # A timeout, throttling or server failure can have an uncertain outcome.
    # Inspect a bounded body only to categorize it; never retain or log it.
    if error.code not in (400, 401, 403, 404, 409, 422):
        return None
    try:
        body = error.read(32769)
    except (OSError, ValueError):
        body = b''
    message = body[:32768].decode('utf-8', errors='replace').lower()
    category = 'request_rejected'
    if error.code == 401: category = 'authentication_failed'
    elif error.code == 403: category = 'permission_denied'
    elif error.code == 404: category = 'pod_not_found'
    elif re.search(r'(no|not enough|insufficient|unavailable|not available).{0,65}(gpu|capacity|resources)|(gpu|capacity|resources).{0,65}(unavailable|not available|insufficient)', message):
        category = 'capacity_unavailable'
    return ActionRejected(http_status=error.code, category=category)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class RunpodAPI:
    def __init__(self, token, *, opener=None, timeout=15):
        if not isinstance(token, str) or not token.strip() or '\n' in token or '\r' in token:
            raise RunpodAPIError('Runpod credential is missing or invalid.')
        self._token = token.strip()
        self._opener = opener or build_opener(NoRedirect())
        self._timeout = timeout

    def _request(self, pod_id, action=None):
        if not isinstance(pod_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', pod_id):
            raise RunpodAPIError('Invalid Pod identity.')
        if action not in (None, 'start', 'stop'):
            raise RunpodAPIError('Unsupported Pod action.')
        url = 'https://api.runpod.io/v2/pods/' + pod_id
        headers = {'Authorization': 'Bearer ' + self._token, 'Accept': 'application/json'}
        payload = None
        method = 'GET'
        if action:
            url += '/action'
            payload = json.dumps({'action': action}, separators=(',', ':')).encode('utf-8')
            headers['Content-Type'] = 'application/json'
            method = 'POST'
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError('oversized response')
            result = json.loads(data)
            if not isinstance(result, dict) or result.get('id') != pod_id:
                raise ValueError('unverified response')
            return result
        except HTTPError as exc:
            if action:
                if action == 'start':
                    rejected = rejected_start(exc)
                    if rejected is not None:
                        raise rejected from None
                raise ActionOutcomeUnknown('Runpod action outcome is unknown; reconcile manually before retrying.',
                                           http_status=exc.code) from None
            raise RunpodAPIError('Runpod Pod status is unavailable.') from None
        except (URLError, OSError, TimeoutError, ValueError, TypeError):
            if action:
                raise ActionOutcomeUnknown('Runpod action outcome is unknown; reconcile manually before retrying.') from None
            raise RunpodAPIError('Runpod Pod status is unavailable.') from None

    def status(self, pod_id):
        return self._request(pod_id)

    def transition(self, pod_id, action):
        # Low-level transport only. Never expose directly to scheduling code.
        if action not in ('start', 'stop'):
            raise RunpodAPIError('Unsupported Pod action.')
        return self._request(pod_id, action)

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
        except (HTTPError, URLError, OSError, TimeoutError, ValueError, TypeError):
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

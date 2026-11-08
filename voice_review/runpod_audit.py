#!/usr/bin/env python3
"""Read-only Runpod v2 Pod inventory; never starts, stops or prints secrets."""
import getpass
import json
import math
import os
import re
import sys
import warnings
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler


class AuditError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get_json(path, token, params=None):
    if not re.fullmatch(r'/pods(?:/[A-Za-z0-9_-]{1,80})?', path):
        raise AuditError('Unsupported Runpod API path.')
    url = 'https://api.runpod.io/v2' + path
    if params:
        url += '?' + urlencode(params)
    request = Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}, method='GET')
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(2_000_001)
    except HTTPError as exc:
        raise AuditError('Runpod API returned HTTP ' + str(exc.code) + '.') from None
    except (OSError, URLError, TimeoutError):
        raise AuditError('Runpod API could not be reached.') from None
    if len(raw) > 2_000_000:
        raise AuditError('Runpod API response exceeds the safe limit.')
    try:
        result = json.loads(raw)
    except (ValueError, TypeError):
        raise AuditError('Runpod API returned invalid data.') from None
    if not isinstance(result, dict):
        raise AuditError('Runpod API returned invalid data.')
    return result


def list_pods(token, *, request=get_json):
    pods, cursor, seen = [], None, set()
    for _ in range(20):
        params = {'limit': 100}
        if cursor:
            params['cursor'] = cursor
        page = request('/pods', token, params)
        if not isinstance(page.get('pods'), list) or not isinstance(page.get('pagination'), dict):
            raise AuditError('Runpod Pod inventory is incomplete.')
        pods.extend(page['pods'])
        pagination = page['pagination']
        if pagination.get('hasNextPage') is False:
            return pods
        cursor = pagination.get('nextCursor')
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise AuditError('Runpod Pod inventory pagination is incomplete.')
        seen.add(cursor)
    raise AuditError('Runpod Pod inventory exceeds the safe limit.')


def safe_summary(pod):
    if not isinstance(pod, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(pod.get('id', ''))):
        raise AuditError('Runpod returned an invalid Pod identity.')
    gpu = pod.get('gpu') if isinstance(pod.get('gpu'), dict) else {}
    mounts = pod.get('mounts') if isinstance(pod.get('mounts'), dict) else {}
    ssh = pod.get('ssh') if isinstance(pod.get('ssh'), dict) else {}
    direct = ssh.get('direct') if isinstance(ssh.get('direct'), dict) else {}
    host, port = direct.get('host'), direct.get('port')
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9.:-]{1,253}', host):
        host = None
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        port = None
    cost = pod.get('cost')
    if isinstance(cost, bool) or not isinstance(cost, (float, int)) or not math.isfinite(cost) or not 0 <= cost <= 1000:
        cost = None
    status = pod.get('status') if pod.get('status') in ('PROVISIONING', 'STARTING', 'RUNNING', 'EXITED', 'ERROR', 'TERMINATED') else 'OTHER'
    model = gpu.get('id')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9 ._-]{1,100}', model):
        model = None
    count = gpu.get('count')
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 128:
        count = None
    return {'id': pod['id'], 'status': status, 'gpu_model': model,
            'gpu_count': count, 'hourly_compute_usd': cost,
            'storage_kinds': [kind for kind in ('persistent', 'network', 'global') if mounts.get(kind)],
            'direct_ssh_host': host, 'direct_ssh_port': port,
            'locked': pod.get('locked')}


def main():
    token = os.environ.get('RUNPOD_API_KEY', '').strip()
    if not token:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            token = getpass.getpass('Runpod API key (hidden; Enter skips): ').strip()
    if not token:
        print('Runpod audit skipped; no request made.')
        return
    items = list_pods(token)
    print('Pods found:', len(items))
    for raw in items:
        summary = safe_summary(raw)
        print(json.dumps(summary, ensure_ascii=True))
    print('Read-only audit complete. No Pod was started, stopped or changed.')
    print('Stopped Pods may still incur storage charges.')


if __name__ == '__main__':
    try:
        main()
    except (AuditError, getpass.GetPassWarning, EOFError) as exc:
        print('Runpod audit stopped:', str(exc) if isinstance(exc, AuditError) else type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)

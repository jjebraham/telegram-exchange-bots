"""Read-only ElevenLabs voice discovery; no synthesis, account changes or posting."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

import reel_voice_registry as registry


class DiscoveryError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(path, params, key):
    if path not in ('/v2/voices', '/v1/shared-voices'):
        raise DiscoveryError('Unsupported voice lookup.')
    url = 'https://api.elevenlabs.io' + path + '?' + urlencode(params)
    req = Request(url, headers={'xi-api-key': key, 'Accept': 'application/json'})
    try:
        with build_opener(NoRedirect()).open(req, timeout=15) as response:
            raw = response.read(4_000_001)
    except HTTPError as exc:
        raise DiscoveryError('HTTP ' + str(exc.code)) from None
    except (OSError, URLError, TimeoutError):
        raise DiscoveryError('Connection unavailable') from None
    if len(raw) > 4_000_000:
        raise DiscoveryError('Response too large')
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        raise DiscoveryError('Invalid response') from None
    if not isinstance(body, dict) or not isinstance(body.get('voices'), list):
        raise DiscoveryError('Invalid response')
    return body


def account_voices(key, *, get=_get):
    rows, token, seen = [], None, set()
    for _ in range(20):
        params = {'page_size': 100}
        if token:
            params['next_page_token'] = token
        page = get('/v2/voices', params, key)
        rows.extend(page['voices'])
        if page.get('has_more') is False:
            return rows
        token = page.get('next_page_token')
        if not isinstance(token, str) or not token or token in seen:
            raise DiscoveryError('Voice inventory pagination is incomplete')
        seen.add(token)
    raise DiscoveryError('Voice inventory exceeds the safe page limit')


def shared_matches(name, key, *, get=_get):
    matches = []
    for page_number in range(2):
        page = get('/v1/shared-voices', {'search': name, 'page_size': 100, 'page': page_number}, key)
        for row in page['voices']:
            if (isinstance(row, dict) and isinstance(row.get('name'), str) and
                    row['name'].strip().casefold() == name.casefold() and
                    isinstance(row.get('voice_id'), str) and re.fullmatch(r'[A-Za-z0-9]{20}', row['voice_id'])):
                matches.append({'name': row['name'], 'voice_id': row['voice_id']})
        if page.get('has_more') is False:
            return matches, False
    return matches, True


def inspect(key, *, get=_get):
    if not isinstance(key, str) or not key.strip():
        raise DiscoveryError('An ElevenLabs API key is required')
    account = account_voices(key, get=get)
    report = []
    missing = []
    for name, configured_id in registry.CANDIDATES:
        matches = [{'name': str(row.get('name', ''))[:100], 'voice_id': row.get('voice_id')}
                   for row in account if isinstance(row, dict) and
                   (row.get('voice_id') == configured_id if configured_id else
                    isinstance(row.get('name'), str) and row['name'].strip().casefold() == name.casefold())]
        matches = [row for row in matches if isinstance(row['voice_id'], str) and re.fullmatch(r'[A-Za-z0-9]{20}', row['voice_id'])]
        result = {'name': name, 'configured_id': configured_id, 'account_matches': matches,
                  'shared_matches': [], 'shared_search_incomplete': False}
        report.append(result)
        if not matches:
            missing.append(result)
    def lookup(row):
        try:
            found, incomplete = shared_matches(row['name'], key, get=get)
            return row['name'], found, incomplete, None
        except DiscoveryError as exc:
            return row['name'], [], False, str(exc)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(lookup, row) for row in missing]):
            name, found, incomplete, error = future.result()
            target = next(row for row in report if row['name'] == name)
            target.update(shared_matches=found, shared_search_incomplete=incomplete, shared_error=error)
    return report


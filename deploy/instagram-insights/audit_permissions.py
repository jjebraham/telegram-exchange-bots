#!/usr/bin/env python3
"""Inspect current token scopes using the same Meta app; do not rotate credentials."""
from __future__ import annotations

import getpass
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import time
from urllib.request import build_opener


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    import instagram_insights_data as data
    import instagram_post_insights as app
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        raise data.InsightsError('Run as the existing publisher user without sudo.')
    graph = data.Graph()
    spec = importlib.util.spec_from_file_location('kiani_insights_token_audit', root / 'deploy/instagram-rates/setup_long_lived_token.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    setup.urlopen = build_opener(data.NoRedirect()).open
    print('Read-only audit of the CURRENT Page token. No token rotation, publishing or deletion.')
    print('Enter the same Meta app credentials locally; they are never printed or saved.')
    app_id = input('Meta App ID: ').strip()
    if not app_id.isdigit():
        raise data.InsightsError('Meta App ID must contain digits.')
    secret = getpass.getpass('Meta App Secret (hidden): ').strip()
    if not secret:
        raise data.InsightsError('Meta App Secret is required to inspect the token.')
    client = setup.MetaClient(graph.version, app_id, secret)
    client.remember(graph.token)
    try:
        inspected = client.inspect(graph.token, 'PAGE')
        identity = client.get(graph.account_id, {'fields': 'id,username'}, graph.token)
    except setup.SetupError as exc:
        raise data.InsightsError(client.redact(str(exc))) from None
    if str(identity.get('id')) != graph.account_id:
        raise data.InsightsError('The audited token does not identify the configured Instagram account.')
    scopes = inspected.get('scopes')
    if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
        raise data.InsightsError('Meta returned no usable granted scopes.')
    required = {'instagram_manage_insights', 'instagram_manage_contents', 'instagram_basic', 'instagram_content_publish'}
    missing = sorted(required - set(scopes))
    proof = dict(app_id=app_id, account_id=graph.account_id,
        token_sha256=hashlib.sha256(graph.token.encode()).hexdigest(), verified_at=time.time(),
        scopes=sorted(set(scopes)), expires_at=setup.timestamp(inspected, 'expires_at'),
        data_access_expires_at=int(inspected.get('data_access_expires_at', 0) or 0))
    for key in ('expires_at', 'data_access_expires_at'):
        if proof[key] and proof[key] <= time.time():
            raise data.InsightsError('Token/data access is expired.')
    with app.locked(data.STATE / 'collector.lock'):
        con = data.database(data.STATE / 'insights.sqlite3')
        try:
            data.bind_account(con, graph.account_id)
            if missing:
                data.set_setting(con, 'permission_proof', None)
                print('Missing required scopes:', ', '.join(missing))
                print('News deletion remains disabled. Grant the missing scopes to the same Meta app and renew the Page token using the existing token setup flow.')
                return 1
            data.set_setting(con, 'permission_proof', proof)
        finally:
            con.close()
    print('Verified: current token grants insights, news-media management and existing publishing access.')
    print('Only the token fingerprint, account/app IDs, scope names and expiry were saved privately.')
    print('No Instagram content was changed. Activate the reviewed news policy separately.')
    return 0


if __name__ == '__main__':
    try:
        os.umask(0o077)
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('Permission audit cancelled; no credential update or content change.')
        raise SystemExit(1)
    except Exception as exc:
        # Even diagnostic error strings can include URLs or credentials. Print
        # only the exception class, never the raw body/traceback/request URL.
        detail = str(exc) if type(exc).__name__ == 'InsightsError' else type(exc).__name__
        print('Permission audit failed:', detail, '| No credential update or content change.', file=sys.stderr)
        raise SystemExit(1)

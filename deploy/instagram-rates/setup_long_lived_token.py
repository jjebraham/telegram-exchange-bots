#!/usr/bin/env python3
"""Obtain and validate a Page token, then atomically save it for the cron job.

Run as the Instagram publisher's Linux user. Secrets are prompted without echo,
used only for Meta requests, and never printed. The App Secret is not persisted.
This command does not publish media.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import shlex
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class SetupError(RuntimeError):
    pass


class MetaClient:
    def __init__(self, version: str, app_id: str, secret: str):
        self.base = f"https://graph.facebook.com/{version}"
        self.app_id = app_id
        self.secret = secret
        self.app_token = f"{app_id}|{secret}"
        self.secrets = [secret, self.app_token]

    def remember(self, token: str) -> str:
        if not isinstance(token, str) or not token.strip():
            raise SetupError("Meta did not return an access token")
        token = token.strip()
        self.secrets.append(token)
        return token

    def redact(self, message: str) -> str:
        for value in sorted(self.secrets, key=len, reverse=True):
            if value:
                message = message.replace(value, "[redacted]")
        return message

    def get(self, path: str, fields: dict | None = None, token: str | None = None) -> dict:
        fields = dict(fields or {})
        headers = {"Accept": "application/json", "User-Agent": "Kiani-TokenSetup/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            if token != self.app_token:
                fields["appsecret_proof"] = hmac.new(
                    self.secret.encode(), token.encode(), hashlib.sha256
                ).hexdigest()
        request = Request(f"{self.base}/{path}?{urlencode(fields)}", headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except HTTPError as exc:
            try:
                error = json.loads(exc.read(8192)).get("error", {})
                detail = self.redact(str(error.get("message", "Request rejected")))
                code = error.get("code", "unknown")
            except (ValueError, AttributeError):
                detail, code = "Request rejected", "unknown"
            raise SetupError(f"Meta HTTP {exc.code}, code {code}: {detail}") from None
        except (URLError, TimeoutError, OSError, ValueError):
            # Exception text can contain the secret-bearing request URL.
            raise SetupError("Meta request failed; check connectivity and try again") from None
        if not isinstance(payload, dict) or "error" in payload:
            raise SetupError("Meta returned an unexpected response")
        return payload

    def inspect(self, token: str, kind: str) -> dict:
        data = self.get("debug_token", {"input_token": token}, self.app_token).get("data")
        if not isinstance(data, dict) or data.get("is_valid") is not True:
            raise SetupError("Token is invalid; generate a fresh User Token for this app")
        if str(data.get("app_id")) != self.app_id:
            raise SetupError("The token belongs to a different Meta app")
        if data.get("type") != kind:
            raise SetupError(f"Expected token type {kind}; received {data.get('type')}")
        return data


def env_value(source: str, key: str) -> str | None:
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=(.*)$")
    found = []
    for line in source.splitlines():
        match = pattern.match(line)
        if match:
            parts = shlex.split(match.group(1), comments=True)
            if len(parts) != 1:
                raise SetupError(f"Invalid environment setting: {key}")
            found.append(parts[0])
    if len(found) > 1:
        raise SetupError(f"Duplicate environment setting: {key}")
    return found[0] if found else None


def timestamp(data: dict, key: str) -> int:
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError):
        raise SetupError(f"Token debugger did not return a valid {key}") from None


def local_date(value: int) -> str:
    return datetime.fromtimestamp(value, ZoneInfo("Europe/Istanbul")).isoformat()


def find_page(client: MetaClient, user_token: str, page_id: str) -> dict:
    fields = {"fields": "id,name,access_token,instagram_business_account", "limit": 100}
    for _ in range(20):
        payload = client.get("me/accounts", fields, user_token)
        pages = payload.get("data")
        if not isinstance(pages, list):
            raise SetupError("Meta did not return the user's Pages")
        for page in pages:
            if isinstance(page, dict) and str(page.get("id")) == page_id:
                return page
        paging = payload.get("paging", {})
        after = paging.get("cursors", {}).get("after")
        if not paging.get("next") or not after:
            break
        fields["after"] = after
    raise SetupError("Kiani Page was not returned; grant this app access to that Page")


def save_token(path: Path, original: str, token: str) -> Path:
    if path.read_text(encoding="utf-8") != original:
        raise SetupError("Environment file changed during setup; run the helper again")
    pattern = re.compile(r"^\s*(?:export\s+)?INSTAGRAM_ACCESS_TOKEN\s*=")
    lines, replaced = [], False
    for line in original.splitlines(keepends=True):
        if pattern.match(line):
            if not replaced:
                lines.append(f"INSTAGRAM_ACCESS_TOKEN={shlex.quote(token)}\n")
                replaced = True
        else:
            lines.append(line)
    if not replaced:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"INSTAGRAM_ACCESS_TOKEN={shlex.quote(token)}\n")

    backup_fd, backup_name = tempfile.mkstemp(prefix=path.name + ".backup-", dir=path.parent)
    os.close(backup_fd)
    backup = Path(backup_name)
    shutil.copyfile(path, backup)
    backup.chmod(0o600)

    fd, temporary = tempfile.mkstemp(prefix=path.name + ".new-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("".join(lines))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path.home() / ".kiani-instagram.env")
    parser.add_argument("--page-id", default="1287244881149876")
    parser.add_argument("--instagram-id", default="17841411127622820")
    args = parser.parse_args()
    path = args.env_file.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise SetupError("Provide the existing regular publisher environment file")
    if path.stat().st_uid != os.geteuid():
        raise SetupError("Run as the owner of the publisher environment file")
    original = path.read_text(encoding="utf-8")
    version = env_value(original, "INSTAGRAM_GRAPH_API_VERSION")
    if not version or not re.fullmatch(r"v\d+\.\d+", version):
        raise SetupError("Set INSTAGRAM_GRAPH_API_VERSION in the environment file first")
    if env_value(original, "INSTAGRAM_USER_ID") != args.instagram_id:
        raise SetupError("Environment Instagram ID does not match the requested account")

    print("Use a fresh USER token for the same app, with Pages and Instagram publishing permissions.")
    app_id = input("Meta App ID: ").strip()
    if not app_id.isdigit():
        raise SetupError("Meta App ID must contain digits")
    secret = getpass.getpass("Meta App Secret: ").strip()
    if not secret:
        raise SetupError("Meta App Secret is required")
    client = MetaClient(version, app_id, secret)
    fresh = client.remember(getpass.getpass("Fresh Graph API Explorer USER token: "))
    client.inspect(fresh, "USER")

    extended = client.remember(client.get("oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": app_id,
        "client_secret": secret, "fb_exchange_token": fresh,
    }).get("access_token"))
    extended_data = client.inspect(extended, "USER")
    extended_expiry = timestamp(extended_data, "expires_at")
    if extended_expiry and extended_expiry < time.time() + 7 * 86400:
        raise SetupError("The exchanged User Token still expires within seven days")

    page = find_page(client, extended, args.page_id)
    linked = page.get("instagram_business_account", {})
    if str(linked.get("id")) != args.instagram_id:
        raise SetupError("Selected Page is not linked to the expected Instagram account")
    page_token = client.remember(page.get("access_token"))
    data = client.inspect(page_token, "PAGE")
    if data.get("profile_id") and str(data["profile_id"]) != args.page_id:
        raise SetupError("Returned Page token belongs to a different Page")
    expires = timestamp(data, "expires_at")
    if expires != 0:
        raise SetupError(f"Page token has a fixed expiry ({local_date(expires)}); environment unchanged")
    if "instagram_content_publish" not in data.get("scopes", []):
        raise SetupError("Page token lacks instagram_content_publish permission")
    access_expiry = int(data.get("data_access_expires_at", 0) or 0)
    if access_expiry and access_expiry <= time.time():
        raise SetupError("Page token's data access has already expired")
    identity = client.get(args.instagram_id, {"fields": "id,username"}, page_token)
    if str(identity.get("id")) != args.instagram_id:
        raise SetupError("New token could not verify the expected Instagram account")

    backup = save_token(path, original, page_token)
    print(f"Saved validated PAGE token for @{identity.get('username')} to {path}")
    print("Token expiry: no fixed expiry reported (expires_at=0).")
    if access_expiry:
        print(f"Data-access expiry: {local_date(access_expiry)}; reauthorization may be needed then.")
    print("Page/admin/app access changes can still invalidate the token.")
    print(f"Previous environment backup: {backup}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SetupError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print("Setup cancelled; no credential update completed.")
        raise SystemExit(1)


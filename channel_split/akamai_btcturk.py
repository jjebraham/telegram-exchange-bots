"""Fetch the fixed public USDT/TRY ticker through the pinned Akamai bridge."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import stat
import subprocess
import time

HOST = "139.162.186.28"
HOST_LINE = "139.162.186.28 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEnTEGelzvtZGAbgDtRPDBEDpre/9+Gx+ubQC4jJHCrO"
SELECTOR = "btcturk_usdt_try"
MAX_AGE_SECONDS = 90


def _number(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid BTCTurk numeric field") from exc
    if not number.is_finite():
        raise ValueError("Non-finite BTCTurk numeric field")
    return number


def fetch_btcturk_snapshot(timeout=7):
    folder = Path("/home/kianirad2020/.ssh")
    key = folder / "kiani_akamai_rates_ed25519"
    known = folder / "kiani_akamai_rates_known_hosts"
    for path in (key, known):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("Invalid Akamai SSH identity or host pin file")
    if known.read_text().strip() != HOST_LINE:
        raise RuntimeError("Akamai SSH host pin does not match")
    command = [
        "ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known}",
        "-o", "GlobalKnownHostsFile=/dev/null", "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=4", "-i", str(key), f"root@{HOST}", SELECTOR,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"Akamai BTCTurk transport failed (exit {result.returncode})")
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        from google_rate_fallback import fetch as fetch_google
        envelope = fetch_google(SELECTOR)
    else:
        if len(result.stdout) > 1024 * 1024:
            raise ValueError("Akamai BTCTurk response exceeds limit")
        envelope = json.loads(result.stdout)
    if (envelope.get("ok") is not True or envelope.get("protocol") != 1
            or envelope.get("selector") != SELECTOR):
        raise ValueError("Invalid Akamai BTCTurk transport envelope")
    observed = datetime.fromisoformat(envelope["observed_at_utc"].replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("Akamai response timestamp has no timezone")
    observed_epoch = observed.timestamp()
    now = time.time()
    if not -5 <= now - observed_epoch <= 30:
        raise ValueError("Akamai BTCTurk transport response is stale")
    headers = envelope["response_headers"]
    http_date = parsedate_to_datetime(headers["date"]).timestamp()
    http_age = _number(headers.get("age", 0))
    if not 0 <= http_age <= 30 or not -5 <= now - http_date <= 30:
        raise ValueError("BTCTurk HTTP response is stale")
    payload = envelope["data"]
    if payload.get("success") is not True:
        raise ValueError("BTCTurk API did not report success")
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("BTCTurk ticker is missing or ambiguous")
    row = rows[0]
    if (row.get("pair") != "USDTTRY" or row.get("numeratorSymbol") != "USDT"
            or row.get("denominatorSymbol") != "TRY"):
        raise ValueError("BTCTurk ticker currency mismatch")
    price = _number(row["last"])
    ticker_epoch = float(_number(row["timestamp"]) / 1000)
    proof_epoch = min(ticker_epoch, observed_epoch, http_date, now)
    if price <= 0 or not -5 <= now - ticker_epoch < MAX_AGE_SECONDS:
        raise ValueError("BTCTurk ticker is invalid or expired")
    if not 0 <= now - proof_epoch < MAX_AGE_SECONDS:
        raise ValueError("BTCTurk market proof expired")
    return {"price": price, "proof_epoch": proof_epoch,
            "observed_epoch": observed_epoch,
            "transport": envelope.get('transport_route', 'akamai-restricted-ssh'),
            "outbound_ip": envelope.get('outbound_ip', HOST)}

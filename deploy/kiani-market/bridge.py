#!/usr/bin/env python3
# Kiani fixed-endpoint SSH rate bridge v1
"""Read-only fixed public endpoints; intended only for an SSH forced command."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

URLS = {'nobitex_book': 'https://apiv2.nobitex.ir/v3/orderbook/all', 'nobitex_stats': 'https://apiv2.nobitex.ir/market/stats?srcCurrency=usdt&dstCurrency=rls', 'wallex_markets': 'https://api.wallex.ir/v1/markets', 'tabdeal_depth': 'https://api1.tabdeal.org/r/api/v1/depth?symbol=USDTIRT&limit=50', 'ramzinex_pairs': 'https://publicapi.ramzinex.com/exchange/api/v1.0/exchange/pairs', 'ramzinex_book': 'https://publicapi.ramzinex.com/exchange/api/v1.0/exchange/orderbooks/11/buys_sells', 'raastin_depth': 'https://api.raastin.com/api/v1/market/depth/USDTIRT/', 'exir_books': 'https://api.exir.io/v2/orderbooks', 'exir_book': 'https://api.exir.io/v2/orderbook?symbol=usdt-irt', 'wallex_depth': 'https://api.wallex.ir/v1/depth?symbol=USDTTMN', 'wallex_trades': 'https://api.wallex.ir/v1/trades?symbol=USDTTMN', 'tabdeal_trades': 'https://api1.tabdeal.org/r/api/v1/trades?symbol=USDTIRT&limit=3', 'raastin_state': 'https://api.raastin.com/api/v1/market/symbols/?name=USDTIRT', 'exir_state': 'https://api.exir.io/v2/constants', 'bitpin_markets': 'https://api.bitpin.ir/api/v1/mkt/markets/', 'bitpin_book': 'https://api.bitpin.ir/api/v1/mth/orderbook/USDT_IRT/', 'bitpin_trades': 'https://api.bitpin.ir/api/v1/mth/matches/USDT_IRT/'}

URLS["btcturk_usdt_try"] = "https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY"
MAX_BYTES = 16 * 1024 * 1024

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def reject_constant(value):
    raise ValueError("non-finite JSON constant")


def public_stream_snapshot(selector):
    import stat
    name = "nobitex.json" if selector == "nobitex_live" else "nobitex-stats.json"
    path = Path("/var/lib/kiani-market-stream") / name
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size > MAX_BYTES:
            raise ValueError("unsafe public stream snapshot")
        value = json.load(handle)
    stamp = datetime.fromisoformat(value["observed_at_utc"])
    if stamp.tzinfo is None or not -5 <= time.time() - stamp.timestamp() <= 20:
        raise ValueError("public stream snapshot is stale")
    if value.get("protocol") != 1 or value.get("ok") is not True or value.get("selector") != selector:
        raise ValueError("invalid public stream envelope")
    return value

def request(selector):
    if selector in ("nobitex_live", "nobitex_live_stats"):
        return public_stream_snapshot(selector)
    if selector == "health":
        return {"ok": True, "protocol": 1, "transport": "restricted-ssh",
                "effective_uid": os.geteuid(), "observed_at_utc": utcnow()}
    if selector not in URLS:
        raise ValueError("unknown endpoint selector")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="kiani-rate-") as tmp:
        body = Path(tmp) / "body.json"
        headers = Path(tmp) / "headers.txt"
        command = [
            "/usr/bin/curl", "-4", "--noproxy", "*", "--proto", "=https",
            "--max-redirs", "0", "--connect-timeout", "4", "--max-time", "12",
            "--max-filesize", str(MAX_BYTES), "--silent", "--show-error",
            "--compressed", "--header", "Accept: application/json",
            "--header", "Cache-Control: no-cache", "--header", "Pragma: no-cache",
            "--dump-header", str(headers), "--output", str(body),
            "--write-out", "%{http_code}", URLS[selector],
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=15,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent"},
        )
        if result.returncode:
            raise RuntimeError("curl failed (exit %s)" % result.returncode)
        status = result.stdout.strip()
        if status != "200":
            raise RuntimeError("upstream HTTP status %s" % status[:12])
        if not body.is_file() or body.stat().st_size > MAX_BYTES:
            raise ValueError("upstream body exceeds limit or is missing")
        if not headers.is_file() or headers.stat().st_size > 128 * 1024:
            raise ValueError("upstream headers exceed limit or are missing")
        data = json.loads(body.read_bytes(), parse_constant=reject_constant)
        if not isinstance(data, (dict, list)):
            raise ValueError("upstream JSON is not an object or array")
        permitted = {"date", "age", "cache-control", "etag", "last-modified",
                     "content-type", "via", "x-cache", "cf-cache-status"}
        metadata = {}
        for line in headers.read_text(errors="replace").splitlines():
            if line.startswith("HTTP/"):
                metadata = {}
            elif ":" in line:
                key, value = line.split(":", 1)
                if key.lower() in permitted:
                    metadata[key.lower()] = value.strip()[:300]
        return {"ok": True, "protocol": 1, "selector": selector,
                "observed_at_utc": utcnow(),
                "request_duration_seconds": round(time.monotonic() - started, 3),
                "response_headers": metadata, "data": data}

def main():
    try:
        if os.geteuid() == 0:
            raise PermissionError("bridge must execute as an unprivileged user")
        if len(sys.argv) != 2:
            raise ValueError("one fixed endpoint selector is required")
        result = request(sys.argv[1])
        print(json.dumps(result, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "protocol": 1,
                          "error": type(exc).__name__, "detail": str(exc)[:180]}))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

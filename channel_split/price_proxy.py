#!/usr/bin/env python3
"""Shared outbound HTTP helper using the same proxy pool as Kiani rates.

Configuration intentionally matches kiani-exchange/backend/app/price_cache.py:
PRICE_PROXY_HOSTS, PRICE_PROXY_USERNAME, PRICE_PROXY_PASSWORD,
PRICE_PROXY_MAX_RETRIES, RATE_HTTP_TIMEOUT_SECONDS.

Unlike the backend module, values are read at request time because
publish_channels.py loads channel_split/.env after importing modules.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener, urlopen

logger = logging.getLogger(__name__)


def _split_items(raw: str) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in re.split(r"[;,]", raw) if item.strip()]


def _proxy_url(host: str, username: str = "", password: str = "") -> str:
    host = host.strip()
    if host.startswith("http://") or host.startswith("https://"):
        parsed = urlsplit(host)
        clean_host = parsed.hostname or ""
        if parsed.port:
            clean_host = f"{clean_host}:{parsed.port}"
        scheme = parsed.scheme or "http"
    else:
        clean_host = host
        scheme = "http"

    if not clean_host:
        raise ValueError("invalid_price_proxy_host")

    username = username.strip()
    password = password.strip()
    if username or password:
        user = quote(username, safe="")
        secret = quote(password, safe="")
        auth = f"{user}:{secret}@"
    else:
        auth = ""

    return f"{scheme}://{auth}{clean_host}"


def _redacted_proxy(proxy_url: str | None) -> str:
    if not proxy_url:
        return "direct"
    try:
        parsed = urlsplit(proxy_url)
        host = parsed.hostname or "unknown"
        netloc = host if parsed.port is None else f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme or "http", netloc, "", "", ""))
    except Exception:
        return "configured-proxy"


def _safe_error(exc: Exception, proxy_url: str | None = None) -> str:
    text = str(exc)
    if proxy_url:
        text = text.replace(proxy_url, _redacted_proxy(proxy_url))
    text = re.sub(
        r"(?i)(https?://)([^/@:\s]+):([^/@\s]+)@",
        r"\1***:***@",
        text,
    )
    return text[:500]


def _timeout_seconds() -> float:
    try:
        return max(
            1.0,
            min(float(os.getenv("RATE_HTTP_TIMEOUT_SECONDS", "4")), 15.0),
        )
    except ValueError:
        return 4.0


def _max_retries() -> int:
    try:
        return max(
            1,
            min(int(os.getenv("PRICE_PROXY_MAX_RETRIES", "2")), 5),
        )
    except ValueError:
        return 2


def _fetch_once(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float,
    proxy_url: str | None = None,
):
    request = Request(url, data=data, headers=headers or {}, method=method)

    if not proxy_url:
        return urlopen(request, timeout=timeout)

    handler = ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = build_opener(handler)
    return opener.open(request, timeout=timeout)


def fetch_json_with_price_proxy(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float | None = None,
):
    """Fetch JSON direct or through the configured Kiani price proxy pool.

    Behavior mirrors the live Kiani backend:
    - no PRICE_PROXY_HOSTS -> one direct request;
    - configured proxy pool -> shuffle and retry proxies;
    - proxy credentials stay separate from host list and are redacted in errors.
    """
    timeout_value = timeout if timeout is not None else _timeout_seconds()
    hosts = _split_items(os.getenv("PRICE_PROXY_HOSTS", ""))
    username = os.getenv("PRICE_PROXY_USERNAME", "")
    password = os.getenv("PRICE_PROXY_PASSWORD", "")

    if not hosts:
        try:
            with _fetch_once(
                url,
                headers=headers,
                data=data,
                method=method,
                timeout=timeout_value,
            ) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"direct_http_{exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"direct_fetch_failed:{_safe_error(exc)}") from exc

    shuffled = hosts.copy()
    random.shuffle(shuffled)
    retries = min(_max_retries(), len(shuffled))
    last_error: Exception | None = None

    for attempt, host in enumerate(shuffled[:retries], start=1):
        proxy_url = None
        try:
            proxy_url = _proxy_url(host, username, password)
            with _fetch_once(
                url,
                headers=headers,
                data=data,
                method=method,
                timeout=timeout_value,
                proxy_url=proxy_url,
            ) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Price fetch attempt %s via %s failed: %s",
                attempt,
                _redacted_proxy(proxy_url),
                _safe_error(exc, proxy_url),
            )

    raise RuntimeError(
        "all_price_proxy_attempts_failed:"
        + (type(last_error).__name__ if last_error else "unknown")
    )

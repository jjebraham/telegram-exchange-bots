#!/usr/bin/env python3
"""Shared outbound HTTP helper using the same proxy pool as Kiani rates.

Configuration and network behavior intentionally match
kiani-exchange/backend/app/price_cache.py:

PRICE_PROXY_HOSTS
PRICE_PROXY_USERNAME
PRICE_PROXY_PASSWORD
PRICE_PROXY_MAX_RETRIES
RATE_HTTP_TIMEOUT_SECONDS

Values are read at request time because publish_channels.py loads
channel_split/.env after importing modules.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from urllib.parse import quote, urlsplit, urlunsplit

logger = logging.getLogger(__name__)


def _split_items(raw: str) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in re.split(r"[;,]", raw) if item.strip()]


def _proxy_url(host: str, username: str = "", password: str = "") -> str:
    """Build the authenticated proxy URL exactly like the Kiani backend."""
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


async def _fetch_once_aiohttp(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float,
    proxy_url: str | None = None,
):
    """Use aiohttp exactly like kiani-exchange/backend/app/price_cache.py."""
    try:
        import aiohttp
    except ImportError as exc:
        raise RuntimeError(
            "aiohttp_not_installed: run this publisher with a Python environment "
            "that has aiohttp installed"
        ) from exc

    request_method = method or ("POST" if data is not None else "GET")
    client_timeout = aiohttp.ClientTimeout(total=timeout)

    async with aiohttp.ClientSession() as session:
        async with session.request(
            request_method,
            url,
            headers=headers,
            data=data,
            proxy=proxy_url,
            timeout=client_timeout,
        ) as response:
            response.raise_for_status()
            return await response.json(content_type=None)


async def _fetch_json_with_price_proxy_async(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float | None = None,
):
    timeout_value = timeout if timeout is not None else _timeout_seconds()
    hosts = _split_items(os.getenv("PRICE_PROXY_HOSTS", ""))
    username = os.getenv("PRICE_PROXY_USERNAME", "")
    password = os.getenv("PRICE_PROXY_PASSWORD", "")

    if not hosts:
        try:
            return await _fetch_once_aiohttp(
                url,
                headers=headers,
                data=data,
                method=method,
                timeout=timeout_value,
            )
        except Exception as exc:
            raise RuntimeError(
                f"direct_fetch_failed:{_safe_error(exc)}"
            ) from exc

    shuffled = hosts.copy()
    random.shuffle(shuffled)
    retries = min(_max_retries(), len(shuffled))
    last_error: Exception | None = None

    for attempt, host in enumerate(shuffled[:retries], start=1):
        proxy_url = None
        try:
            proxy_url = _proxy_url(host, username, password)
            return await _fetch_once_aiohttp(
                url,
                headers=headers,
                data=data,
                method=method,
                timeout=timeout_value,
                proxy_url=proxy_url,
            )
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


def fetch_json_with_price_proxy(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float | None = None,
):
    """Synchronous wrapper for the CLI around the Kiani aiohttp proxy flow."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            _fetch_json_with_price_proxy_async(
                url,
                headers=headers,
                data=data,
                method=method,
                timeout=timeout,
            )
        )

    raise RuntimeError(
        "fetch_json_with_price_proxy cannot be called from an active asyncio loop; "
        "use _fetch_json_with_price_proxy_async instead"
    )


async def _fetch_json_direct_then_price_proxy_async(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float | None = None,
):
    """Try direct first, then fall back to the configured Kiani proxy pool.

    This mirrors the live Kiani backend's BTCTurk pattern.
    """
    timeout_value = timeout if timeout is not None else _timeout_seconds()

    try:
        return await _fetch_once_aiohttp(
            url,
            headers=headers,
            data=data,
            method=method,
            timeout=timeout_value,
        )
    except Exception as direct_exc:
        logger.warning(
            "Direct price fetch failed, trying proxy pool: %s",
            _safe_error(direct_exc),
        )

    hosts = _split_items(os.getenv("PRICE_PROXY_HOSTS", ""))
    if not hosts:
        raise RuntimeError(
            "direct_fetch_failed_and_no_proxy_pool"
        ) from direct_exc

    return await _fetch_json_with_price_proxy_async(
        url,
        headers=headers,
        data=data,
        method=method,
        timeout=timeout_value,
    )


def fetch_json_direct_then_price_proxy(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    method: str | None = None,
    timeout: float | None = None,
):
    """Synchronous CLI wrapper: direct first, then PRICE_PROXY_* fallback."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            _fetch_json_direct_then_price_proxy_async(
                url,
                headers=headers,
                data=data,
                method=method,
                timeout=timeout,
            )
        )

    raise RuntimeError(
        "fetch_json_direct_then_price_proxy cannot be called from an active asyncio loop; "
        "use _fetch_json_direct_then_price_proxy_async instead"
    )

import asyncio
import logging
import os
import random
import re
import time
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp

logger = logging.getLogger(__name__)


def _split_items(raw: str) -> list[str]:
    """Split comma/semicolon separated configuration without logging it."""
    if not raw:
        return []
    return [item.strip() for item in re.split(r"[;,]", raw) if item.strip()]


PRICE_PROXY_HOSTS = _split_items(os.getenv("PRICE_PROXY_HOSTS", ""))
PRICE_PROXY_USERNAME = os.getenv("PRICE_PROXY_USERNAME", "").strip()
PRICE_PROXY_PASSWORD = os.getenv("PRICE_PROXY_PASSWORD", "").strip()
WALLEX_API_KEY = os.getenv("WALLEX_API_KEY", "").strip()
WALLEX_BASE_URL = os.getenv("WALLEX_BASE_URL", "https://api.wallex.ir/v1").rstrip("/")

try:
    PRICE_PROXY_MAX_RETRIES = max(1, min(int(os.getenv("PRICE_PROXY_MAX_RETRIES", "2")), 5))
except ValueError:
    PRICE_PROXY_MAX_RETRIES = 2

try:
    RATE_HTTP_TIMEOUT_SECONDS = max(1.0, min(float(os.getenv("RATE_HTTP_TIMEOUT_SECONDS", "4")), 15.0))
except ValueError:
    RATE_HTTP_TIMEOUT_SECONDS = 4.0


def _proxy_url(host: str) -> str:
    """Build a proxy URL from environment configuration.

    PRICE_PROXY_HOSTS should normally contain host:port entries. Full URLs are
    accepted for compatibility, but credentials should be supplied separately
    through PRICE_PROXY_USERNAME / PRICE_PROXY_PASSWORD.
    """
    host = host.strip()
    if host.startswith("http://") or host.startswith("https://"):
        parsed = urlsplit(host)
        # If a full URL was supplied, remove any embedded credentials first.
        clean_host = parsed.hostname or ""
        if parsed.port:
            clean_host = f"{clean_host}:{parsed.port}"
        scheme = parsed.scheme or "http"
    else:
        clean_host = host
        scheme = "http"

    if not clean_host:
        raise ValueError("invalid_price_proxy_host")

    if PRICE_PROXY_USERNAME or PRICE_PROXY_PASSWORD:
        user = quote(PRICE_PROXY_USERNAME, safe="")
        password = quote(PRICE_PROXY_PASSWORD, safe="")
        auth = f"{user}:{password}@"
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
    """Return a short exception string with URL credentials removed."""
    text = str(exc)
    if proxy_url:
        text = text.replace(proxy_url, _redacted_proxy(proxy_url))
    text = re.sub(
        r"(?i)(https?://)([^/@:\s]+):([^/@\s]+)@",
        r"\1***:***@",
        text,
    )
    return text[:500]


class PriceCache:
    def __init__(self):
        self.usdt_irr = None
        self.usdt_irr_time = 0
        self.usdt_try = None
        self.usdt_try_time = 0
        self.fetch_interval = 600  # seconds

    async def _fetch_once(self, url, headers=None, is_json=True, proxy_url=None):
        timeout = aiohttp.ClientTimeout(total=RATE_HTTP_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                url,
                headers=headers,
                proxy=proxy_url,
                timeout=timeout,
            ) as resp:
                resp.raise_for_status()
                if is_json:
                    return await resp.json()
                return await resp.text()

    async def _fetch_with_proxy_retry(self, url, headers=None, is_json=True, max_retries=None):
        """Fetch with optional environment-configured proxy retries.

        When no proxy hosts are configured this performs one direct request.
        Proxy credentials and full authenticated URLs are never written to logs.
        """
        retries = max_retries or PRICE_PROXY_MAX_RETRIES

        if not PRICE_PROXY_HOSTS:
            return await self._fetch_once(url, headers=headers, is_json=is_json)

        hosts = PRICE_PROXY_HOSTS.copy()
        random.shuffle(hosts)
        last_error = None

        for attempt, host in enumerate(hosts[:retries], start=1):
            proxy_url = None
            try:
                proxy_url = _proxy_url(host)
                return await self._fetch_once(
                    url,
                    headers=headers,
                    is_json=is_json,
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
            f"all_price_proxy_attempts_failed:{type(last_error).__name__ if last_error else 'unknown'}"
        )

    async def fetch_usdt_irr(self) -> float:
        primary_url = "https://flask-9l1dbb.chbk.app/proxy/usdt-to-rls"
        try:
            data = await self._fetch_once(primary_url, is_json=True)
            rate = data.get("usdt_to_rls")
            if rate:
                return float(rate)
            raise ValueError("no_usdt_to_rls_in_primary_response")
        except Exception as exc:
            logger.warning("Primary USDT-IRR failed: %s", _safe_error(exc))

        # Fallback: Wallex market data. The markets endpoint can be queried
        # without embedding any API key in source; add X-API-KEY only when the
        # operator explicitly configures WALLEX_API_KEY in the environment.
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            if WALLEX_API_KEY:
                headers["X-API-KEY"] = WALLEX_API_KEY

            data = await self._fetch_with_proxy_retry(
                f"{WALLEX_BASE_URL}/markets",
                headers=headers,
                is_json=True,
            )
            symbols = data.get("result", {}).get("symbols", {})
            usdt_data = symbols.get("USDTTMN")
            if not usdt_data:
                raise ValueError("USDTTMN_not_found")
            last_price = usdt_data.get("stats", {}).get("lastPrice")
            if last_price:
                return float(last_price) * 10  # Toman -> Rial
            raise ValueError("wallex_last_price_missing")
        except Exception as exc:
            logger.error("Wallex USDT-IRR fallback failed: %s", _safe_error(exc))
            raise

    async def fetch_usdt_try(self) -> float:
        url = "https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY"
        try:
            data = await self._fetch_once(url, is_json=True)
        except Exception as direct_exc:
            logger.warning("Primary USDT-TRY failed: %s", _safe_error(direct_exc))
            data = await self._fetch_with_proxy_retry(url, is_json=True)

        items = data.get("data", [])
        if items:
            return float(items[0].get("last", 0))
        raise ValueError("btcturk_data_missing")

    async def get_usdt_irr(self) -> float:
        now = time.time()
        if self.usdt_irr is None or (now - self.usdt_irr_time) > self.fetch_interval:
            self.usdt_irr = await self.fetch_usdt_irr()
            self.usdt_irr_time = now
        return self.usdt_irr

    async def get_usdt_try(self) -> float:
        now = time.time()
        if self.usdt_try is None or (now - self.usdt_try_time) > self.fetch_interval:
            self.usdt_try = await self.fetch_usdt_try()
            self.usdt_try_time = now
        return self.usdt_try

    async def warm_cache(self):
        try:
            usdt_irr, usdt_try = await asyncio.gather(
                self.fetch_usdt_irr(),
                self.fetch_usdt_try(),
            )
            now = time.time()
            self.usdt_irr = usdt_irr
            self.usdt_irr_time = now
            self.usdt_try = usdt_try
            self.usdt_try_time = now
        except Exception as exc:
            logger.warning("Rate warm-up failed: %s", _safe_error(exc))


price_cache = PriceCache()

import time
import logging
import aiohttp

logger = logging.getLogger(__name__)

PROXY_URL = "http://jjebraham-25:Amir1234@p.webshare.io:80"
WALLEX_API_KEY = "15064|7tVDd4NDBYmATAe4lWTUQSTzj0v7ceTELEv6u6zG"
WALLEX_BASE_URL = "https://api.wallex.ir/v1"


class PriceCache:
    def __init__(self):
        self.usdt_irr = None
        self.usdt_irr_time = 0
        self.usdt_try = None
        self.usdt_try_time = 0
        self.fetch_interval = 600  # seconds

    async def fetch_usdt_irr(self) -> float:
        # Primary: flask proxy
        primary_url = "https://flask-9l1dbb.chbk.app/proxy/usdt-to-rls"
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    primary_url, proxy=PROXY_URL, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    rate = data.get("usdt_to_rls")
                    if rate:
                        return float(rate)
                    raise ValueError("no usdt_to_rls in primary response")
        except Exception as e:
            logger.warning(f"Primary USDT-IRR failed: {e}")

        # Fallback: Wallex API
        try:
            headers = {"X-API-KEY": WALLEX_API_KEY, "User-Agent": "Mozilla/5.0"}
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    f"{WALLEX_BASE_URL}/markets",
                    headers=headers,
                    proxy=PROXY_URL,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    body = await resp.json()
                    symbols = body.get("result", {}).get("symbols", {})
                    usdt_data = symbols.get("USDTTMN")
                    if not usdt_data:
                        raise ValueError("USDTTMN not found in Wallex response")
                    stats = usdt_data.get("stats", {})
                    last_price = stats.get("lastPrice")
                    if last_price:
                        return float(last_price) * 10  # Convert Toman to Rial
                    raise ValueError("No lastPrice in Wallex data")
        except Exception as e:
            logger.error(f"Wallex USDT-IRR fallback failed: {e}")
            raise

    async def fetch_usdt_try(self) -> float:
        url = "https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY"
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    url, proxy=PROXY_URL, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    items = data.get("data", [])
                    if items:
                        return float(items[0].get("last", 0))
                    raise ValueError("No data in BTCTurk response")
        except Exception as e:
            logger.error(f"USDT-TRY fetch failed: {e}")
            raise

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


price_cache = PriceCache()

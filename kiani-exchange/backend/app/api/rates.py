import time
import logging
import aiohttp
from fastapi import APIRouter

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory rate cache
_rate_cache = {
    "usdt_irr": None,
    "usdt_irr_time": 0,
    "usdt_try": None,
    "usdt_try_time": 0,
}
CACHE_TTL = 300  # 5 minutes


async def fetch_usdt_irr() -> float | None:
    primary_url = "https://flask-9l1dbb.chbk.app/proxy/usdt-to-rls"
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(primary_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                data = await resp.json()
                rate = data.get("usdt_to_rls")
                if rate:
                    return float(rate)
    except Exception as e:
        logger.warning(f"Primary USDT-IRR failed: {e}")

    # Fallback: Wallex API
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                "https://api.wallex.ir/v1/markets",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()
                symbols = body.get("result", {}).get("symbols", {})
                usdt_data = symbols.get("USDTTMN")
                if usdt_data:
                    price_tmn = float(usdt_data["stats"]["lastPrice"])
                    if price_tmn > 0:
                        return price_tmn * 10
    except Exception as e:
        logger.error(f"Wallex fallback failed: {e}")

    return None


async def fetch_usdt_try() -> float | None:
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                "https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                arr = data.get("data", [])
                if arr:
                    return float(arr[0].get("last", 0))
    except Exception as e:
        logger.error(f"USDT-TRY fetch failed: {e}")
    return None


async def get_cached_rates() -> dict:
    now = time.time()

    if _rate_cache["usdt_irr"] is None or (now - _rate_cache["usdt_irr_time"]) > CACHE_TTL:
        rate = await fetch_usdt_irr()
        if rate:
            _rate_cache["usdt_irr"] = rate
            _rate_cache["usdt_irr_time"] = now

    if _rate_cache["usdt_try"] is None or (now - _rate_cache["usdt_try_time"]) > CACHE_TTL:
        rate = await fetch_usdt_try()
        if rate:
            _rate_cache["usdt_try"] = rate
            _rate_cache["usdt_try_time"] = now

    usdt_irr = _rate_cache["usdt_irr"]
    usdt_try = _rate_cache["usdt_try"]

    result = {
        "usdt_irr": usdt_irr,
        "usdt_try": usdt_try,
        "try_irr": None,
    }

    if usdt_irr and usdt_try:
        result["try_irr"] = round(usdt_irr / usdt_try, 2)

    return result


def round_to_nearest_10(x: float) -> int:
    return int(round(x / 10.0) * 10)


@router.get("/rates")
async def get_rates():
    rates = await get_cached_rates()
    if not rates["usdt_irr"] and not rates["usdt_try"]:
        return {"status": "error", "message": "Unable to fetch rates"}

    usdt_irr = rates["usdt_irr"]
    usdt_try = rates["usdt_try"]
    toman = usdt_irr / 10 if usdt_irr else None

    computed = {}
    if toman and usdt_try:
        computed["buy_lira"] = round_to_nearest_10(toman / usdt_try * 1.02)
        computed["sell_lira"] = round_to_nearest_10(toman / usdt_try * 0.97)
        computed["lira_to_tether"] = round(usdt_try * 1.02, 2)
        computed["tether_to_lira"] = round(usdt_try * 0.98, 2)

    if toman:
        computed["buy_tether"] = round_to_nearest_10(toman * 1.01)
        computed["sell_tether"] = round_to_nearest_10(toman * 0.99)

    return {
        "status": "success",
        "raw": rates,
        "computed": computed,
        "timestamp": time.time(),
    }

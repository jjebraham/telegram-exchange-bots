from fastapi import APIRouter, HTTPException
from ..price_cache import price_cache

router = APIRouter()


@router.get("/rates/current")
async def get_current_rates():
    try:
        usdt_irr = await price_cache.get_usdt_irr()
        usdt_try = await price_cache.get_usdt_try()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch rates at this time",
        )

    return {
        "rates": {
            "USDT_IRR": usdt_irr,
            "USDT_TRY": usdt_try,
        }
    }

from fastapi import APIRouter, HTTPException
from ..price_cache import price_cache
from ..exchange_math import derive_rates
from ..rate_settings import get_rate_settings

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

    settings = get_rate_settings()
    calculated = derive_rates(usdt_irr, usdt_try, settings)

    return {
        "rates": {
            "USDT_IRR": usdt_irr,
            "USDT_TRY": usdt_try,
            "buy_lira": calculated["buy_lira"],
            "sell_lira": calculated["sell_lira"],
            "buy_usdt": calculated["buy_usdt"],
            "sell_usdt": calculated["sell_usdt"],
            "usdt_to_lira": calculated["usdt_to_lira"],
            "lira_to_usdt": calculated["lira_to_usdt"],
            "foreign_payment": round((usdt_irr / 10 * settings["foreign_payment_factor"]) / 10) * 10,
        },
        "settings": settings,
    }

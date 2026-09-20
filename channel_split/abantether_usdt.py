#!/usr/bin/env python3
"""Direct AbanTether USDT/IRT OTC ticker adapter for AlanChande.

Official public endpoint:
GET https://api.abantether.com/api/v1/manager/otc/ticker?coin=USDT

The documented USDT/IRT market uses Toman (IRT) directly:
- buy_price: price a customer pays to buy USDT
- sell_price: price a customer receives when selling USDT
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from price_proxy import fetch_json_direct_then_price_proxy

ABANTETHER_TICKER_URL = "https://api.abantether.com/api/v1/manager/otc/ticker"


@dataclass(frozen=True)
class AbanTetherUsdtQuote:
    buy_toman: Decimal
    sell_toman: Decimal
    active: bool
    buy_max: Decimal | None
    sell_max: Decimal | None


def _decimal(value, field: str, *, optional: bool = False) -> Decimal | None:
    if optional and value in (None, "", "-"):
        return None

    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"AbanTether field {field!r} is not numeric") from exc

    if not result.is_finite() or result <= 0:
        raise ValueError(f"AbanTether field {field!r} must be positive")
    return result


def parse_abantether_usdt_ticker(payload: dict) -> AbanTetherUsdtQuote:
    if not isinstance(payload, dict):
        raise ValueError("AbanTether ticker response is not an object")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("AbanTether ticker response has no data object")

    markets = data.get("markets")
    if not isinstance(markets, dict):
        raise ValueError("AbanTether ticker response has no markets object")

    market = markets.get("USDTIRT")
    if not isinstance(market, dict):
        # Defensive fallback in case the key changes while symbol remains USDT.
        market = next(
            (
                row
                for key, row in markets.items()
                if isinstance(row, dict)
                and str(key).upper().endswith("IRT")
                and str(row.get("symbol", "")).upper() == "USDT"
            ),
            None,
        )

    if not isinstance(market, dict):
        raise ValueError("AbanTether response has no USDT/IRT market")

    active = market.get("active")
    if active is not True:
        raise ValueError("AbanTether USDT/IRT market is not active")

    buy_toman = _decimal(market.get("buy_price"), "buy_price")
    sell_toman = _decimal(market.get("sell_price"), "sell_price")
    assert isinstance(buy_toman, Decimal)
    assert isinstance(sell_toman, Decimal)

    if sell_toman >= buy_toman:
        raise ValueError("AbanTether buy/sell prices are crossed or invalid")

    return AbanTetherUsdtQuote(
        buy_toman=buy_toman,
        sell_toman=sell_toman,
        active=True,
        buy_max=_decimal(market.get("buy_max"), "buy_max", optional=True),
        sell_max=_decimal(market.get("sell_max"), "sell_max", optional=True),
    )


def fetch_abantether_usdt(timeout: float | None = None) -> AbanTetherUsdtQuote:
    query = urlencode({"coin": "USDT"})
    payload = fetch_json_direct_then_price_proxy(
        f"{ABANTETHER_TICKER_URL}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "AlanChande-DirectMarket/1.0",
        },
        timeout=timeout,
    )
    return parse_abantether_usdt_ticker(payload)


def _fmt_toman(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal('1'))):,}"


def build_abantether_usdt_post(quote: AbanTetherUsdtQuote) -> str:
    spread = quote.buy_toman - quote.sell_toman

    return "\n".join(
        [
            "💎 <b>تتر | آبان‌تتر</b>",
            "",
            f"🛒 <b>خرید تتر</b>　<code>{_fmt_toman(quote.buy_toman)}</code> تومان",
            f"💵 <b>فروش تتر</b>　<code>{_fmt_toman(quote.sell_toman)}</code> تومان",
            "",
            f"↔️ <b>فاصله خرید/فروش</b>　<code>{_fmt_toman(spread)}</code> تومان",
        ]
    )

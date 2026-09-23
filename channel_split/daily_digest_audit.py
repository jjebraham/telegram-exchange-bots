#!/usr/bin/env python3
"""Read-only first-stage source coverage audit for the proposed noon digest.

This tool calls only existing AlanChande data collectors. It sends no Telegram
messages, schedules no timers, and writes no accepted price history. CONSENSUS
means price agreement among configured provider families in this probe, not
approval to publish: production history/freshness and missing adapters must
still be checked by the final digest safety gate.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from hybrid_usdt_compare import collect_hybrid_usdt_snapshot
from iran_fx import fetch_iran_open_market_fx
from iran_fx_adonis import fetch_adonis_try_sell_toman
from iran_fx_pashizi import fetch_pashizi_iran_fx
from iran_gold import fetch_iran_gold_market
from iran_gold_external_verifier import fetch_dolarchand_iran_gold
from market_safety import (
    SafetyObservation, evaluate_observation, usdt_observations,
)

FX = ("USD", "EUR", "AED", "TRY", "CNY", "CAD", "AUD", "GBP", "AFN")
GOLD = (
    "سکه امامی", "سکه بهار آزادی", "نیم سکه",
    "ربع سکه", "مثقال طلا", "طلای ۱۸ عیار",
)
CRYPTO = (
    "BTC", "ETH", "BNB", "SHIB", "ADA",
    "DOGE", "TON", "NOT", "SOL", "XRP",
)


def check_row(
    name: str,
    values: Mapping[str, Decimal],
    *,
    tolerance_pct: Decimal = Decimal("2"),
) -> tuple[str, str]:
    """Evaluate provider agreement without touching production history."""
    check = evaluate_observation(
        SafetyObservation(
            market_key=name,
            source_values=values,
            min_sources=2,
            max_source_deviation_pct=tolerance_pct,
        )
    )
    if check.decision == "VERIFIED" and check.reference_value is not None:
        return "CONSENSUS", str(check.reference_value)
    return check.decision, "—"


def _try_fetch(label: str, fetcher: Any) -> Any | None:
    try:
        data = fetcher()
    except Exception as exc:
        # Type only: URL, proxy and other exception details could be sensitive.
        print(f"SOURCE {label}: FAILED ({type(exc).__name__})")
        return None
    print(f"SOURCE {label}: FETCHED")
    return data


def _show(section: str, label: str, values: Mapping[str, Decimal]) -> str:
    status, price = check_row(label, values)
    families = ",".join(sorted(values)) if values else "none"
    print(f"{section:<7} {label:<18} {status:<12} sources={families} value={price}")
    return status


def run_audit() -> None:
    print("READ-ONLY noon digest inventory: no Telegram send, no database writes")
    print("Preliminary consensus only; TGJU timestamp/history checks still needed.")
    print("Pashizi and Dolarchand: maximum age 120 minutes.")
    print()

    fx_tgju = _try_fetch("TGJU FX", fetch_iran_open_market_fx) or {}
    fx_pashizi = _try_fetch(
        "Pashizi FX", lambda: fetch_pashizi_iran_fx(max_age_minutes=120)
    ) or {}
    adonis_try = _try_fetch("Adonis TRY", fetch_adonis_try_sell_toman)

    fx_ok = 0
    print("\n===== REQUESTED IRAN FX =====")
    for code in FX:
        sources = {}
        if code in fx_tgju:
            sources["tgju"] = fx_tgju[code]
        if code in fx_pashizi:
            sources["pashizi"] = fx_pashizi[code]
        if code == "TRY" and adonis_try is not None:
            sources["adonis"] = adonis_try
        fx_ok += _show("FX", code, sources) == "CONSENSUS"

    gold_tgju = _try_fetch("TGJU gold", fetch_iran_gold_market)
    gold_dolarchand = _try_fetch(
        "Dolarchand gold", lambda: fetch_dolarchand_iran_gold(max_age_minutes=120)
    ) or {}

    gold_ok = 0
    print("\n===== REQUESTED IRAN GOLD =====")
    for label in GOLD:
        sources = {}
        if gold_tgju is not None:
            raw_rial = gold_tgju.coin_prices_rial.get(label)
            if label == "طلای ۱۸ عیار":
                raw_rial = gold_tgju.gold18_rial
            elif label == "مثقال طلا":
                raw_rial = gold_tgju.mesghal_rial
            if raw_rial is not None:
                sources["tgju"] = Decimal(str(raw_rial)) / Decimal("10")
        if label in gold_dolarchand:
            sources["dolarchand"] = gold_dolarchand[label]
        gold_ok += _show("GOLD", label, sources) == "CONSENSUS"

    print("\n===== REQUESTED USDT/TOMAN =====")
    usdt_ok = False
    snapshot = _try_fetch("hybrid exchange USDT", collect_hybrid_usdt_snapshot)
    if snapshot is not None:
        try:
            observations = usdt_observations(snapshot.quotes)
            check = evaluate_observation(observations[0])
            families = ",".join(sorted(check.source_values)) or "none"
            print(
                f"USDT    USDT/TOMAN         {check.decision:<12} "
                f"sources={families} value="
                f"{check.reference_value if check.decision == 'VERIFIED' else '—'}"
            )
            usdt_ok = check.decision == "VERIFIED"
        except Exception as exc:
            print(f"USDT    USDT/TOMAN         BLOCKED (probe {type(exc).__name__})")
    else:
        print("USDT    USDT/TOMAN         BLOCKED (collector unavailable)")

    print("\n===== ADDITIONAL ADAPTERS REQUIRED =====")
    print("FX      100 IQD            NOT IMPLEMENTED: TGJU dedicated + Pashizi 100 IQD")
    print("GOLD    XAU/USD ounce      NOT IMPLEMENTED: TGJU ounce + licensed spot feed")
    for symbol in CRYPTO:
        print(
            f"CRYPTO  {symbol:<18} NOT IMPLEMENTED: "
            "independent CoinGecko and exchange feed"
        )
    print()
    print(
        f"EXISTING COVERAGE: {fx_ok}/{len(FX)} FX, "
        f"{gold_ok}/{len(GOLD)} gold, "
        f"{int(usdt_ok)}/1 USDT preliminary consensus"
    )
    print("DIGEST PUBLICATION: DISABLED pending missing adapters, "
          "per-asset freshness, history and 2-source live validation.")


if __name__ == "__main__":
    run_audit()

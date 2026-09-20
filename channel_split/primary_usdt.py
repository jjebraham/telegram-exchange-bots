#!/usr/bin/env python3
"""Primary AlanChande USDT comparison with TGJU fallback.

Normal path:
    direct exchange APIs (Wallex / Exir / Ramzinex)

Fallback path:
    TGJU comparison table, only when fewer than two direct sources survive.
"""

from __future__ import annotations

import logging
from typing import Callable

from direct_usdt_compare import fetch_and_build_direct_usdt_comparison
from iran_usdt import build_usdt_exchange_post, fetch_usdt_exchange_quotes

logger = logging.getLogger(__name__)


def build_primary_usdt_post(
    *,
    direct_builder: Callable[[], str] = fetch_and_build_direct_usdt_comparison,
    fallback_fetcher=fetch_usdt_exchange_quotes,
    fallback_builder=build_usdt_exchange_post,
) -> str:
    """Prefer direct exchange APIs; use TGJU only if direct quorum fails."""
    try:
        return direct_builder()
    except Exception as exc:
        logger.warning(
            "Direct USDT quorum failed; using TGJU fallback: %s: %s",
            type(exc).__name__,
            str(exc)[:300],
        )

    fallback_post = fallback_builder(fallback_fetcher())
    return (
        fallback_post
        + "\n\n"
        + "⚠️ <i>داده مستقیم کافی نبود؛ این بروزرسانی از منبع پشتیبان بازار تهیه شده است.</i>"
    )

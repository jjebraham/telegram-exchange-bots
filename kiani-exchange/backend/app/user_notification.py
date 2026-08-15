import asyncio
import logging
import os
from pathlib import Path

import aiohttp
from dotenv import dotenv_values

from .database import get_db
from .api.profile import ensure_profile_schema

logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[1]


def get_user_bot_token() -> str:
    explicit = os.getenv("TELEGRAM_USER_BOT_TOKEN", "").strip()
    if explicit:
        return explicit
    values = dotenv_values(BACKEND_DIR / ".env")
    return str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()


async def send_user_message(user_id: int, text: str) -> bool:
    ensure_profile_schema()
    token = get_user_bot_token()
    if not token:
        logger.warning("Customer Telegram bot token is not configured")
        return False

    with get_db() as conn:
        row = conn.execute("SELECT telegram_chat_id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not row["telegram_chat_id"]:
        return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": int(row["telegram_chat_id"]), "text": text},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    return True
                logger.warning("Customer Telegram send failed HTTP %s", response.status)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("Customer Telegram send failed: %s", exc)
    return False

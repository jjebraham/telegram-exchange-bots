import logging
import os
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)


def _config() -> tuple[str, int]:
    token = (
        os.getenv("TELEGRAM_ADMIN_BOT_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )
    chat_id = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "0") or 0)
    return token, chat_id


async def send_admin_message(message: str) -> bool:
    token, chat_id = _config()
    if not token or not chat_id:
        logger.warning("Admin Telegram notification skipped: token/chat ID not configured")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.error("Admin Telegram notification failed: %s %s", response.status, body[:500])
                    return False
                return True
    except Exception as exc:
        logger.exception("Admin Telegram notification error: %s", exc)
        return False


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")

from __future__ import annotations

import requests


class TelegramPublishError(RuntimeError):
    pass


def send_html_message(*, bot_token: str, chat_id: str, text: str, timeout: float = 12.0) -> dict:
    if not bot_token:
        raise TelegramPublishError("Telegram bot token is empty")
    if not chat_id:
        raise TelegramPublishError("Telegram channel ID is empty")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise TelegramPublishError(f"Telegram send failed: {exc}") from exc

    if not data.get("ok"):
        raise TelegramPublishError(f"Telegram API returned an error: {data}")
    return data

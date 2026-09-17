from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    alanchande_bot_token: str
    alanchande_channel_id: str
    kiani_bot_token: str
    kiani_channel_id: str
    posting_enabled: bool
    timeout_seconds: float
    user_agent: str
    bank_rates_provider: str
    kiani_rates: dict


def load_settings() -> Settings:
    project_dir = Path(__file__).resolve().parents[1]
    load_dotenv(project_dir / ".env")

    raw_kiani = os.getenv("KIANI_RATES_JSON", "").strip()
    kiani_rates = json.loads(raw_kiani) if raw_kiani else {}

    return Settings(
        alanchande_bot_token=os.getenv("ALANCHANDE_BOT_TOKEN", "").strip(),
        alanchande_channel_id=os.getenv("ALANCHANDE_CHANNEL_ID", "").strip(),
        kiani_bot_token=os.getenv("KIANI_BOT_TOKEN", "").strip(),
        kiani_channel_id=os.getenv("KIANI_CHANNEL_ID", "").strip(),
        posting_enabled=os.getenv("POSTING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "12")),
        user_agent=os.getenv("HTTP_USER_AGENT", "AlanChandeChannelPublisher/0.1"),
        bank_rates_provider=os.getenv("BANK_RATES_PROVIDER", "doviz_com").strip(),
        kiani_rates=kiani_rates,
    )

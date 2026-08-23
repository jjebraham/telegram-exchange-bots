"""API settings helpers with environment-safe fallbacks."""

import json
import logging
import os
from typing import Any

from .database import get_db

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            value = json.loads(raw)
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
        except json.JSONDecodeError:
            logger.warning("%s contains invalid JSON; falling back to delimiter parsing", name)
    delimiter = ";" if ";" in raw else ","
    return [item.strip() for item in raw.split(delimiter) if item.strip()]


def init_settings() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_type TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT
            )
            """
        )


def get_api_settings(setting_type: str) -> dict[str, Any]:
    init_settings()
    with get_db() as conn:
        row = conn.execute(
            "SELECT settings_json FROM api_settings WHERE setting_type = ? ORDER BY id DESC LIMIT 1",
            (setting_type,),
        ).fetchone()
    if not row:
        return {}
    try:
        value = json.loads(row["settings_json"])
    except (TypeError, json.JSONDecodeError):
        logger.error("Invalid JSON stored for api_settings type=%s", setting_type)
        return {}
    return value if isinstance(value, dict) else {}


def get_ehraz_settings() -> dict[str, Any]:
    return get_api_settings("ehraz")


def get_ghasedak_settings() -> dict[str, Any]:
    return get_api_settings("ghasedak")


def get_ehraz_token() -> str:
    settings = get_ehraz_settings()
    return str(settings.get("token") or os.getenv("EHRAZ_TOKEN", "")).strip()


def get_ehraz_proxies() -> list[str]:
    settings = get_ehraz_settings()
    value = settings.get("proxy_list")
    if isinstance(value, list):
        proxies = [str(item).strip() for item in value if str(item).strip()]
        if proxies:
            return proxies
    return _env_list("EHRAZ_PROXY_LIST")


def get_ehraz_test_mode() -> bool:
    settings = get_ehraz_settings()
    if "test_mode" in settings:
        return bool(settings.get("test_mode"))
    return _env_bool("KYC_TEST_MODE", False)


def get_ghasedak_api_key() -> str:
    settings = get_ghasedak_settings()
    return str(settings.get("api_key") or os.getenv("GHASEDAK_API_KEY", "")).strip()


def get_ghasedak_template() -> str:
    settings = get_ghasedak_settings()
    return str(settings.get("template_name") or os.getenv("GHASEDAK_TEMPLATE_NAME", "")).strip()


def get_ghasedak_line_number() -> str:
    settings = get_ghasedak_settings()
    return str(settings.get("line_number") or os.getenv("GHASEDAK_LINE_NUMBER", "")).strip()


def get_ghasedak_proxy_format() -> str:
    settings = get_ghasedak_settings()
    return str(settings.get("proxy_format") or os.getenv("GHASEDAK_PROXY_FORMAT", "")).strip()


def get_ghasedak_proxy_pool() -> tuple[int, int]:
    settings = get_ghasedak_settings()
    start = settings.get("proxy_pool_start", os.getenv("GHASEDAK_PROXY_POOL_START", "1"))
    end = settings.get("proxy_pool_end", os.getenv("GHASEDAK_PROXY_POOL_END", "100"))
    try:
        start_int = int(start)
        end_int = int(end)
    except (TypeError, ValueError):
        return (1, 100)
    if start_int < 1 or end_int < start_int:
        return (1, 100)
    return (start_int, end_int)

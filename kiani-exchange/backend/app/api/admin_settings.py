"""Optional admin API-settings endpoints.

This module intentionally contains no provider credentials. Values are loaded
from the database/environment and writes require the bearer-authenticated admin
role. It is not mounted by default in app.main yet; keeping it safe makes future
re-enablement straightforward.
"""

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..admin_auth import AdminIdentity, require_admin_roles
from ..database import get_db

router = APIRouter()
ADMIN_ONLY = require_admin_roles("admin")
ADMIN_SUPPORT = require_admin_roles("admin", "support")


class EhrazSettings(BaseModel):
    enabled: bool = True
    token: str = ""
    test_mode: bool = False
    proxy_list: list[str] = Field(default_factory=list)
    timeout_seconds: int = 6
    max_retries: int = 3


class GhasedakSettings(BaseModel):
    enabled: bool = True
    api_key: str = ""
    template_name: str = ""
    line_number: str = ""
    otp_endpoint: str = "https://gateway.ghasedak.me/rest/api/v1/WebService/SendOtpWithParams"
    simple_endpoint: str = "https://api.ghasedak.me/v2/sms/send/simple"
    proxy_format: str = ""
    proxy_pool_start: int = 1
    proxy_pool_end: int = 100
    timeout_seconds: int = 15
    max_retries: int = 3


class ApiSettingsUpdate(BaseModel):
    ehraz: EhrazSettings | None = None
    ghasedak: GhasedakSettings | None = None


def init_settings_tables() -> None:
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_test_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_type TEXT NOT NULL,
                test_data TEXT NOT NULL,
                result TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _latest(setting_type: str) -> dict[str, Any]:
    init_settings_tables()
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
        return {}
    return value if isinstance(value, dict) else {}


def _masked(settings: dict[str, Any], secret_keys: set[str]) -> dict[str, Any]:
    result = dict(settings)
    for key in secret_keys:
        if result.get(key):
            result[key] = "***configured***"
    if isinstance(result.get("proxy_list"), list):
        result["proxy_list"] = ["***configured proxy***"] * len(result["proxy_list"])
    if result.get("proxy_format"):
        result["proxy_format"] = "***configured***"
    return result


@router.get("/admin/api-settings")
async def get_api_settings(identity: AdminIdentity = Depends(ADMIN_SUPPORT)):
    return {
        "ehraz": _masked(_latest("ehraz"), {"token"}),
        "ghasedak": _masked(_latest("ghasedak"), {"api_key"}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/admin/api-settings/update")
async def update_api_settings(
    update: ApiSettingsUpdate,
    identity: AdminIdentity = Depends(ADMIN_ONLY),
):
    init_settings_tables()
    with get_db() as conn:
        if update.ehraz is not None:
            conn.execute(
                "INSERT INTO api_settings (setting_type, settings_json, updated_by) VALUES (?, ?, ?)",
                ("ehraz", json.dumps(update.ehraz.model_dump()), identity.username),
            )
        if update.ghasedak is not None:
            conn.execute(
                "INSERT INTO api_settings (setting_type, settings_json, updated_by) VALUES (?, ?, ?)",
                ("ghasedak", json.dumps(update.ghasedak.model_dump()), identity.username),
            )
    return {"status": "success"}


@router.get("/admin/api-test-logs")
async def get_test_logs(limit: int = 50, identity: AdminIdentity = Depends(ADMIN_SUPPORT)):
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="invalid_limit")
    init_settings_tables()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, api_type, success, created_at FROM api_test_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"logs": [dict(row) for row in rows]}

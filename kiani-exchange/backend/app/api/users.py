import aiohttp
import asyncio
import random
import logging
import os
import json
import time
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)
from ..database import get_db
from ..rate_settings import get_rate_settings, update_rate_settings
from ..auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user_id,
)

EHRAZ_TOKEN = os.getenv("EHRAZ_TOKEN", "5942b9d62abc20405dadfb2c0f546b669cf1471c")

# Telegram Bot Configuration
# Use environment variables for security
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8278787504:AAGU4jeKIYq4Kw_FNcgA-7_rb3H152aKxMU")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "2043363119"))

# KYC Verification Mode
# Set to True to enable test mode (bypasses EHRAZ for test data)
# Set to False for production (real EHRAZ verification)
KYC_TEST_MODE = False  # DISABLED - Use real EHRAZ API

# List of proxy servers from your configuration
# IMPORTANT: EHRAZ API requires authenticated proxies
# Use the pattern: http://jjebraham-{N}:Amir1234@p.webshare.io:80
# Where N is a number from 1-100 (randomized)

PROXY_LIST = [
    "http://jjebraham-1:Amir1234@p.webshare.io:80",
    "http://jjebraham-2:Amir1234@p.webshare.io:80",
    "http://jjebraham-3:Amir1234@p.webshare.io:80",
    "http://jjebraham-4:Amir1234@p.webshare.io:80",
    "http://jjebraham-5:Amir1234@p.webshare.io:80",
    "http://jjebraham-6:Amir1234@p.webshare.io:80",
    "http://jjebraham-7:Amir1234@p.webshare.io:80",
    "http://jjebraham-8:Amir1234@p.webshare.io:80",
    "http://jjebraham-9:Amir1234@p.webshare.io:80",
    "http://jjebraham-10:Amir1234@p.webshare.io:80",
    "http://jjebraham-11:Amir1234@p.webshare.io:80",
    "http://jjebraham-12:Amir1234@p.webshare.io:80",
    "http://jjebraham-13:Amir1234@p.webshare.io:80",
    "http://jjebraham-14:Amir1234@p.webshare.io:80",
    "http://jjebraham-15:Amir1234@p.webshare.io:80",
    "http://jjebraham-16:Amir1234@p.webshare.io:80",
    "http://jjebraham-17:Amir1234@p.webshare.io:80",
    "http://jjebraham-18:Amir1234@p.webshare.io:80",
    "http://jjebraham-19:Amir1234@p.webshare.io:80",
    "http://jjebraham-20:Amir1234@p.webshare.io:80",
    "http://jjebraham-21:Amir1234@p.webshare.io:80",
    "http://jjebraham-22:Amir1234@p.webshare.io:80",
    "http://jjebraham-23:Amir1234@p.webshare.io:80",
    "http://jjebraham-24:Amir1234@p.webshare.io:80",
    "http://jjebraham-25:Amir1234@p.webshare.io:80",
    "http://jjebraham-26:Amir1234@p.webshare.io:80",
    "http://jjebraham-27:Amir1234@p.webshare.io:80",
    "http://jjebraham-28:Amir1234@p.webshare.io:80",
    "http://jjebraham-29:Amir1234@p.webshare.io:80",
    "http://jjebraham-30:Amir1234@p.webshare.io:80",
    "http://jjebraham-31:Amir1234@p.webshare.io:80",
    "http://jjebraham-32:Amir1234@p.webshare.io:80",
    "http://jjebraham-33:Amir1234@p.webshare.io:80",
    "http://jjebraham-34:Amir1234@p.webshare.io:80",
    "http://jjebraham-35:Amir1234@p.webshare.io:80",
    "http://jjebraham-36:Amir1234@p.webshare.io:80",
    "http://jjebraham-37:Amir1234@p.webshare.io:80",
    "http://jjebraham-38:Amir1234@p.webshare.io:80",
    "http://jjebraham-39:Amir1234@p.webshare.io:80",
    "http://jjebraham-40:Amir1234@p.webshare.io:80",
    "http://jjebraham-41:Amir1234@p.webshare.io:80",
    "http://jjebraham-42:Amir1234@p.webshare.io:80",
    "http://jjebraham-43:Amir1234@p.webshare.io:80",
    "http://jjebraham-44:Amir1234@p.webshare.io:80",
    "http://jjebraham-45:Amir1234@p.webshare.io:80",
    "http://jjebraham-46:Amir1234@p.webshare.io:80",
    "http://jjebraham-47:Amir1234@p.webshare.io:80",
    "http://jjebraham-48:Amir1234@p.webshare.io:80",
    "http://jjebraham-49:Amir1234@p.webshare.io:80",
    "http://jjebraham-50:Amir1234@p.webshare.io:80",
    "http://jjebraham-51:Amir1234@p.webshare.io:80",
    "http://jjebraham-52:Amir1234@p.webshare.io:80",
    "http://jjebraham-53:Amir1234@p.webshare.io:80",
    "http://jjebraham-54:Amir1234@p.webshare.io:80",
    "http://jjebraham-55:Amir1234@p.webshare.io:80",
    "http://jjebraham-56:Amir1234@p.webshare.io:80",
    "http://jjebraham-57:Amir1234@p.webshare.io:80",
    "http://jjebraham-58:Amir1234@p.webshare.io:80",
    "http://jjebraham-59:Amir1234@p.webshare.io:80",
    "http://jjebraham-60:Amir1234@p.webshare.io:80",
    "http://jjebraham-61:Amir1234@p.webshare.io:80",
    "http://jjebraham-62:Amir1234@p.webshare.io:80",
    "http://jjebraham-63:Amir1234@p.webshare.io:80",
    "http://jjebraham-64:Amir1234@p.webshare.io:80",
    "http://jjebraham-65:Amir1234@p.webshare.io:80",
    "http://jjebraham-66:Amir1234@p.webshare.io:80",
    "http://jjebraham-67:Amir1234@p.webshare.io:80",
    "http://jjebraham-68:Amir1234@p.webshare.io:80",
    "http://jjebraham-69:Amir1234@p.webshare.io:80",
    "http://jjebraham-70:Amir1234@p.webshare.io:80",
    "http://jjebraham-71:Amir1234@p.webshare.io:80",
    "http://jjebraham-72:Amir1234@p.webshare.io:80",
    "http://jjebraham-73:Amir1234@p.webshare.io:80",
    "http://jjebraham-74:Amir1234@p.webshare.io:80",
    "http://jjebraham-75:Amir1234@p.webshare.io:80",
    "http://jjebraham-76:Amir1234@p.webshare.io:80",
    "http://jjebraham-77:Amir1234@p.webshare.io:80",
    "http://jjebraham-78:Amir1234@p.webshare.io:80",
    "http://jjebraham-79:Amir1234@p.webshare.io:80",
    "http://jjebraham-80:Amir1234@p.webshare.io:80",
    "http://jjebraham-81:Amir1234@p.webshare.io:80",
    "http://jjebraham-82:Amir1234@p.webshare.io:80",
    "http://jjebraham-83:Amir1234@p.webshare.io:80",
    "http://jjebraham-84:Amir1234@p.webshare.io:80",
    "http://jjebraham-85:Amir1234@p.webshare.io:80",
    "http://jjebraham-86:Amir1234@p.webshare.io:80",
    "http://jjebraham-87:Amir1234@p.webshare.io:80",
    "http://jjebraham-88:Amir1234@p.webshare.io:80",
    "http://jjebraham-89:Amir1234@p.webshare.io:80",
    "http://jjebraham-90:Amir1234@p.webshare.io:80",
    "http://jjebraham-91:Amir1234@p.webshare.io:80",
    "http://jjebraham-92:Amir1234@p.webshare.io:80",
    "http://jjebraham-93:Amir1234@p.webshare.io:80",
    "http://jjebraham-94:Amir1234@p.webshare.io:80",
    "http://jjebraham-95:Amir1234@p.webshare.io:80",
    "http://jjebraham-96:Amir1234@p.webshare.io:80",
    "http://jjebraham-97:Amir1234@p.webshare.io:80",
    "http://jjebraham-98:Amir1234@p.webshare.io:80",
    "http://jjebraham-99:Amir1234@p.webshare.io:80",
    "http://jjebraham-100:Amir1234@p.webshare.io:80",
]

def get_random_proxy():
    """Get a random proxy from the list"""
    proxy = random.choice(PROXY_LIST)
    return proxy  # Return as-is since all proxies now have full URL with auth


async def send_telegram_notification(message: str):
    """Send notification to Telegram admin bot"""
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        logger.warning("Telegram bot token or admin chat ID not configured")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Failed to send Telegram notification: {response.status}")
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")

router = APIRouter()


class RegisterRequest(BaseModel):
    first_name: str
    last_name: str
    national_id: str
    date_of_birth: str
    bank_card_number: str
    phone_number: str
    password: str


class LoginRequest(BaseModel):
    phone_number: str
    password: str


class EhrazRequest(BaseModel):
    cardNumber: str
    nationalCode: str
    birthDate: str


class EhrazMobileRequest(BaseModel):
    nationalCode: str
    mobileNumber: str


class AdminCredentials(BaseModel):
    username: str
    password: str


class FaqRequest(BaseModel):
    username: str
    password: str
    question: str
    answer: str


class AdminResetPasswordRequest(BaseModel):
    username: str
    password: str
    new_password: str


class PasswordResetStartRequest(BaseModel):
    phone_number: str
    channel: str  # bot | sms


class PasswordResetCompleteRequest(BaseModel):
    phone_number: str
    code: str
    new_password: str


class AdminSendMessageRequest(BaseModel):
    username: str
    password: str
    message: str
    user_id: int | None = None


class RegisterCheckRequest(BaseModel):
    phone_number: str
    national_id: str


class AdminRateSettingsUpdateRequest(BaseModel):
    username: str
    password: str
    toman_to_tl_factor: float
    tl_to_toman_factor: float
    buy_usdt_factor: float
    sell_usdt_factor: float
    usdt_to_lira_factor: float
    lira_to_usdt_factor: float
    foreign_payment_factor: float


def _admin_role(username: str, password: str) -> str | None:
    admin_user = os.getenv("ADMIN_PANEL_USERNAME", "admin")
    admin_pass = os.getenv("ADMIN_PANEL_PASSWORD", "admin123")
    support_user = os.getenv("SUPPORT_PANEL_USERNAME", "support")
    support_pass = os.getenv("SUPPORT_PANEL_PASSWORD", "support123")
    viewer_user = os.getenv("VIEWER_PANEL_USERNAME", "viewer")
    viewer_pass = os.getenv("VIEWER_PANEL_PASSWORD", "viewer123")

    if username == admin_user and password == admin_pass:
        return "admin"
    if username == support_user and password == support_pass:
        return "support"
    if username == viewer_user and password == viewer_pass:
        return "viewer"
    return None


def _require_roles(username: str, password: str, allowed: set[str]) -> str:
    role = _admin_role(username, password)
    if role not in allowed:
        raise HTTPException(status_code=401, detail="unauthorized")
    return role


def _is_admin(username: str, password: str) -> bool:
    return _admin_role(username, password) == "admin"


def _write_admin_log(action: str, details: dict | None = None):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            (action, json.dumps(details or {}, ensure_ascii=False)),
        )


def _log_user_activity(action: str, source: str, details: dict | None = None, user_id: int | None = None, phone_number: str | None = None):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO user_activity_logs (user_id, phone_number, action, source, details) VALUES (?, ?, ?, ?, ?)",
            (user_id, phone_number, action, source, json.dumps(details or {}, ensure_ascii=False)),
        )


def _write_ehraz_log(phone_number: str | None, national_id: str | None, endpoint: str, request_payload: dict, response_payload: dict | str, success: bool, error_message: str | None = None):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO ehraz_logs
               (phone_number, national_id, endpoint, request_payload, response_payload, success, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                phone_number,
                national_id,
                endpoint,
                json.dumps(request_payload, ensure_ascii=False),
                json.dumps(response_payload, ensure_ascii=False) if not isinstance(response_payload, str) else response_payload,
                1 if success else 0,
                error_message,
            ),
        )


def _log_kyc_verification(action: str, phone_number: str, national_id: str, details: dict):
    """Log KYC verification steps for admin panel"""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO kyc_verification_logs 
               (phone_number, national_id, action, details)
               VALUES (?, ?, ?, ?)""",
            (
                phone_number,
                national_id,
                action,
                json.dumps(details, ensure_ascii=False),
            ),
        )


def _write_sms_log(phone_number: str, request_payload: dict, response_payload: str, success: bool, error_message: str | None = None):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO sms_logs (phone_number, provider, request_payload, response_payload, success, error_message)
               VALUES (?, 'ghasedak', ?, ?, ?, ?)""",
            (
                phone_number,
                json.dumps(request_payload, ensure_ascii=False),
                response_payload,
                1 if success else 0,
                error_message,
            ),
        )


async def _send_text(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        await session.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)




def _normalize_iran_phone(phone: str) -> str:
    digits = ''.join(ch for ch in phone if ch.isdigit())
    if digits.startswith('98'):
        return '0' + digits[2:]
    if digits.startswith('0098'):
        return '0' + digits[4:]
    return digits


async def _send_ghasedak_sms(phone_number: str, message: str) -> tuple[bool, str]:
    api_key = os.getenv("GHASEDAK_API_KEY", "").strip()
    line_number = os.getenv("GHASEDAK_LINE_NUMBER", "").strip()
    if not api_key:
        return (False, "missing_ghasedak_api_key")

    payload = {
        "receptor": phone_number,
        "message": message,
    }
    if line_number:
        payload["linenumber"] = line_number

    headers = {
        "apikey": api_key,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    
    url = "https://api.ghasedak.me/v2/sms/send/simple"
    
    # Try direct connection first with longer timeout
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                data=payload,
                headers=headers,
                timeout=30,  # Longer timeout for direct
            ) as resp:
                body = await resp.text()
                ok = resp.status == 200
                logger.info("Ghasedak DIRECT response status=%s body=%s", resp.status, body[:500])
                _write_sms_log(phone_number, payload, body[:2000], ok, 
                             f"direct_http_{resp.status}" if not ok else None)
                return (ok, body)
    except asyncio.TimeoutError:
        logger.warning("Ghasedak direct connection timeout after 30s")
        direct_error = "direct_timeout"
    except Exception as exc:
        logger.warning("Ghasedak direct connection failed: %s", exc)
        direct_error = str(exc)
    else:
        direct_error = None
    
    # If direct failed, try with proxies
    if direct_error:
        logger.info("Trying Ghasedak with proxies after direct connection failed: %s", direct_error)
        
        # Fallback with proxy rotation (similar to EHRAZ)
        for attempt in range(3):  # Try 3 times with different proxies
            proxy_url = get_random_proxy()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        data=payload,
                        headers=headers,
                        proxy=proxy_url,
                        timeout=15,
                    ) as resp:
                        body = await resp.text()
                        ok = resp.status == 200
                        logger.info("Ghasedak PROXY response (proxy=%s) status=%s body=%s", 
                                   proxy_url, resp.status, body[:500])
                        _write_sms_log(phone_number, payload, body[:2000], ok, 
                                     f"proxy_http_{resp.status}" if not ok else None)
                        return (ok, body)
            except Exception as exc:
                logger.warning("Ghasedak proxy attempt %d failed (proxy=%s): %s", 
                             attempt + 1, proxy_url, exc)
                continue
    
    # All attempts failed
    error_msg = f"Ghasedak API failed: Direct: {direct_error}, Proxies: all blocked (403)"
    logger.error(error_msg)
    _write_sms_log(phone_number, payload, error_msg, False, error_msg)
    return (False, error_msg)

async def _ehraz_post(url: str, payload: dict, timeout_seconds: int = 6, phone_number: str | None = None, national_id: str | None = None):
    headers = {
        "Authorization": f"Token {EHRAZ_TOKEN}",
        "Content-Type": "application/json",
    }

    # Quick direct attempt first to reduce perceived latency.
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as resp:
                # Try to get response text first for debugging
                response_text = await resp.text()
                
                # Log raw response for debugging
                logger.debug(f"EHRAZ raw response: {response_text[:200]}")
                
                try:
                    data = json.loads(response_text) if response_text.strip() else {}
                except json.JSONDecodeError as json_err:
                    _write_ehraz_log(phone_number, national_id, url, payload, 
                                    {"raw_response": response_text[:500], "json_error": str(json_err)}, 
                                    False, f"json_decode_error")
                    # Return empty dict to continue with proxy fallback
                    data = {}
                
                if resp.status == 200 and data:
                    _write_ehraz_log(phone_number, national_id, url, payload, data, True)
                    return data
                else:
                    error_msg = f"http_{resp.status}" if resp.status != 200 else "empty_or_invalid_response"
                    _write_ehraz_log(phone_number, national_id, url, payload, 
                                    {"status": resp.status, "raw_response": response_text[:500]}, 
                                    False, error_msg)
    except Exception as exc:
        _write_ehraz_log(phone_number, national_id, url, payload, {"error": str(exc)}, False, str(exc))

    # Fallback with proxy rotation.
    for _ in range(2):
        proxy_url = get_random_proxy()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                ) as resp:
                    # Try to get response text first for debugging
                    response_text = await resp.text()
                    
                    try:
                        data = json.loads(response_text) if response_text.strip() else {}
                    except json.JSONDecodeError as json_err:
                        _write_ehraz_log(phone_number, national_id, url, payload, 
                                        {"proxy_raw_response": response_text[:500], "json_error": str(json_err)}, 
                                        False, f"proxy_json_decode_error")
                        # Continue to next proxy attempt
                        continue
                    
                    if resp.status == 200 and data:
                        _write_ehraz_log(phone_number, national_id, url, payload, data, True)
                        return data
                    else:
                        error_msg = f"proxy_http_{resp.status}" if resp.status != 200 else "proxy_empty_response"
                        _write_ehraz_log(phone_number, national_id, url, payload, 
                                        {"status": resp.status, "proxy_raw_response": response_text[:500]}, 
                                        False, error_msg)
        except Exception as exc:
            _write_ehraz_log(phone_number, national_id, url, payload, {"proxy_error": str(exc)}, False, str(exc))
            continue

    _write_ehraz_log(phone_number, national_id, url, payload, {"api_failed": True}, False, "all_attempts_failed")
    raise Exception("EHRAZ API service unavailable - all proxy attempts failed")


def _user_dict(row):
    return {
        "id": row["id"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "phone_number": row["phone_number"],
        "kyc_status": row["kyc_status"],
        "verification_level": row["verification_level"]
        if "verification_level" in row.keys()
        else 1,
        "national_id": row["national_id"] if "national_id" in row.keys() else None,
        "dob": row["dob"] if "dob" in row.keys() else None,
        "bank_card_number": row["bank_card_number"] if "bank_card_number" in row.keys() else None,
    }


@router.post("/users/register/check")
async def check_register_conflicts(req: RegisterCheckRequest):
    phone = _normalize_iran_phone(req.phone_number)
    with get_db() as conn:
        existing_phone = conn.execute("SELECT id FROM users WHERE phone_number = ?", (phone,)).fetchone()
        existing_nid = conn.execute("SELECT id FROM users WHERE national_id = ?", (req.national_id,)).fetchone()
    return {
        "exists_phone": bool(existing_phone),
        "exists_national_id": bool(existing_nid),
    }


@router.post("/users/register")
async def register_user(req: RegisterRequest):
    req.phone_number = _normalize_iran_phone(req.phone_number)
    hashed = hash_password(req.password)
    
    # Log KYC verification start
    _log_kyc_verification("kyc_start", req.phone_number, req.national_id, {
        "step": "start",
        "action": "registration_attempt"
    })

    with get_db() as conn:
        # Step 1: Check if phone number exists in database
        existing_phone = conn.execute(
            "SELECT id FROM users WHERE phone_number = ?",
            (req.phone_number,),
        ).fetchone()
        if existing_phone:
            _log_user_activity("register_conflict_phone", "miniapp", {"phone_number": req.phone_number}, phone_number=req.phone_number)
            _log_kyc_verification("kyc_failed", req.phone_number, req.national_id, {
                "step": "phone_check",
                "action": "phone_already_registered",
                "error": "Phone number already registered"
            })
            raise HTTPException(
                status_code=409,
                detail="already_registered_phone",
            )

        # Step 2: Check if national ID exists in database
        existing_nid = conn.execute(
            "SELECT id FROM users WHERE national_id = ?",
            (req.national_id,),
        ).fetchone()
        if existing_nid:
            _log_user_activity("register_conflict_national_id", "miniapp", {"national_id": req.national_id}, phone_number=req.phone_number)
            _log_kyc_verification("kyc_failed", req.phone_number, req.national_id, {
                "step": "national_id_check",
                "action": "national_id_already_registered",
                "error": "National ID already registered"
            })
            raise HTTPException(status_code=409, detail="already_registered_national_id")

        # Step 3: Check if bank card exists in database
        existing_card = conn.execute(
            "SELECT id FROM users WHERE bank_card_number = ?",
            (req.bank_card_number,),
        ).fetchone()
        if existing_card:
            _log_user_activity("register_conflict_card", "miniapp", {"bank_card_number": req.bank_card_number}, phone_number=req.phone_number)
            _log_kyc_verification("kyc_failed", req.phone_number, req.national_id, {
                "step": "card_check",
                "action": "card_already_registered",
                "error": "Bank card already registered"
            })
            raise HTTPException(status_code=409, detail="already_registered_card")

        # Step 4: Call EHRAZ API to match phone number with national ID
        _log_kyc_verification("kyc_step", req.phone_number, req.national_id, {
            "step": "ehraz_phone_national_match",
            "action": "calling_ehraz_api"
        })
        
        try:
            # Check if we're in test mode and this is test data
            test_phone_prefix = req.phone_number.startswith("0912") or req.phone_number.startswith("0935") or req.phone_number.startswith("0999")
            test_nid_prefix = req.national_id.startswith("00") or req.national_id.startswith("11") or req.national_id == "2091925799"
            
            if KYC_TEST_MODE and test_phone_prefix and test_nid_prefix:
                # Test mode: Simulate successful EHRAZ verification for test data
                _log_kyc_verification("kyc_step", req.phone_number, req.national_id, {
                    "step": "ehraz_phone_national_match",
                    "action": "test_mode_bypass",
                    "note": "Test mode enabled, bypassing EHRAZ for test data"
                })
                
                phone_national_match = {"matched": True}
                card_national_match = {"matched": True}
                
                _log_kyc_verification("kyc_step", req.phone_number, req.national_id, {
                    "step": "ehraz_card_national_match",
                    "action": "test_mode_bypass",
                    "note": "Test mode enabled, bypassing EHRAZ for test data"
                })
            else:
                # Production mode: Real EHRAZ API calls
                # First EHRAZ API call: Match phone number with national ID
                phone_national_match = await _ehraz_post(
                    "https://ehraz.io/api/v1/match/national-with-mobile",
                    {
                        "nationalCode": req.national_id,
                        "mobileNumber": req.phone_number  # Fixed parameter name
                    },
                    phone_number=req.phone_number,
                    national_id=req.national_id
                )
                
                if not phone_national_match.get("matched", False):
                    _log_kyc_verification("kyc_failed", req.phone_number, req.national_id, {
                        "step": "ehraz_phone_national_match",
                        "action": "ehraz_api_failed",
                        "error": "Phone number and national ID do not match",
                        "ehraz_response": phone_national_match
                    })
                    raise HTTPException(
                        status_code=400,
                        detail="phone_national_mismatch",
                    )
                
                _log_kyc_verification("kyc_step", req.phone_number, req.national_id, {
                    "step": "ehraz_phone_national_match",
                    "action": "ehraz_api_success",
                    "ehraz_response": phone_national_match
                })
                
                # Step 5: Call EHRAZ API to match national ID with DOB and bank card
                _log_kyc_verification("kyc_step", req.phone_number, req.national_id, {
                    "step": "ehraz_card_national_match",
                    "action": "calling_ehraz_api"
                })
                
                # Format card number (remove spaces) and date (YYYYMMDD format)
                formatted_card = ''.join(ch for ch in req.bank_card_number if ch.isdigit())
                formatted_dob = ''.join(ch for ch in req.date_of_birth if ch.isdigit())
                
                card_national_match = await _ehraz_post(
                    "https://ehraz.io/api/v1/match/card-with-national",
                    {
                        "nationalCode": req.national_id,
                        "birthDate": formatted_dob,
                        "cardNumber": formatted_card
                    },
                    phone_number=req.phone_number,
                    national_id=req.national_id
                )
                
                if not card_national_match.get("matched", False):
                    _log_kyc_verification("kyc_failed", req.phone_number, req.national_id, {
                        "step": "ehraz_card_national_match",
                        "action": "ehraz_api_failed",
                        "error": "National ID, DOB, and bank card do not match",
                        "ehraz_response": card_national_match
                    })
                    raise HTTPException(
                        status_code=400,
                        detail="card_national_mismatch",
                    )
                
                _log_kyc_verification("kyc_step", req.phone_number, req.national_id, {
                    "step": "ehraz_card_national_match",
                    "action": "ehraz_api_success",
                    "ehraz_response": card_national_match
                })
            
        except HTTPException:
            # Re-raise HTTP exceptions (like phone_national_mismatch)
            raise
        except Exception as e:
            _log_kyc_verification("kyc_failed", req.phone_number, req.national_id, {
                "step": "ehraz_api_call",
                "action": "ehraz_api_error",
                "error": str(e)
            })
            raise HTTPException(
                status_code=500,
                detail="verification_service_error",
            )

        # Step 6: All checks passed, create user
        conn.execute(
            """INSERT INTO users
               (first_name, last_name, national_id, dob,
                bank_card_number, phone_number, password_hash,
                accepted_terms, kyc_status, verification_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'Approved', 2)""",  # Level 2 for full KYC verification
            (
                req.first_name,
                req.last_name,
                req.national_id,
                req.date_of_birth,
                req.bank_card_number,
                req.phone_number,
                hashed,
            ),
        )
        conn.commit()

    # Send notification to admin bot
    notification_message = (
        "📝 <b>ثبت نام جدید</b>\n"
        f"👤 نام: {req.first_name} {req.last_name}\n"
        f"📱 شماره: {req.phone_number}\n"
        f"🆔 کدملی: {req.national_id}\n"
        f"💳 کارت: {req.bank_card_number}\n"
        f"📅 تاریخ: {req.date_of_birth}\n"
        f"⏰ زمان: {asyncio.get_event_loop().time()}"
    )
    await send_telegram_notification(notification_message)

    with get_db() as conn:
        user_row = conn.execute("SELECT id FROM users WHERE phone_number = ?", (req.phone_number,)).fetchone()
    _log_user_activity("register_success", "miniapp", {"national_id": req.national_id}, user_id=user_row["id"] if user_row else None, phone_number=req.phone_number)

    return {"status": "success", "message": "User registered"}


@router.post("/users/login")
async def login_user(req: LoginRequest):
    req.phone_number = _normalize_iran_phone(req.phone_number)
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE phone_number = ?",
            (req.phone_number,),
        ).fetchone()

    if not user or not user["password_hash"]:
        # Send failed login attempt notification
        notification_message = (
            "❌ <b>تلاش ناموفق ورود</b>\n"
            f"📱 شماره: {req.phone_number}\n"
            f"⏰ زمان: {asyncio.get_event_loop().time()}\n"
            f"📝 وضعیت: کاربر یافت نشد"
        )
        await send_telegram_notification(notification_message)
        _log_user_activity("login_failed", "miniapp", {"reason": "user_not_found"}, phone_number=req.phone_number)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(req.password, user["password_hash"]):
        # Send failed login attempt notification
        notification_message = (
            "❌ <b>تلاش ناموفق ورود</b>\n"
            f"📱 شماره: {req.phone_number}\n"
            f"👤 کاربر: {user['first_name']} {user['last_name']}\n"
            f"⏰ زمان: {asyncio.get_event_loop().time()}\n"
            f"📝 وضعیت: رمز عبور اشتباه"
        )
        await send_telegram_notification(notification_message)
        _log_user_activity("login_failed", "miniapp", {"reason": "invalid_password"}, user_id=user["id"], phone_number=req.phone_number)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"user_id": user["id"]})

    # Send successful login notification
    notification_message = (
        "✅ <b>ورود موفق</b>\n"
        f"👤 کاربر: {user['first_name']} {user['last_name']}\n"
        f"📱 شماره: {req.phone_number}\n"
        f"⏰ زمان: {asyncio.get_event_loop().time()}"
    )
    await send_telegram_notification(notification_message)
    _log_user_activity("login_success", "miniapp", {"kyc_status": user["kyc_status"]}, user_id=user["id"], phone_number=req.phone_number)

    return {"token": token, "user": _user_dict(user)}


@router.get("/users/me")
async def get_me(user_id: int = Depends(get_current_user_id)):
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"user": _user_dict(user)}


@router.post("/verify/ehraz")
async def verify_with_ehraz(req: EhrazRequest):
    # Format card number (remove spaces) and date (YYYYMMDD format)
    formatted_card = ''.join(ch for ch in req.cardNumber if ch.isdigit())
    formatted_dob = ''.join(ch for ch in req.birthDate if ch.isdigit())
    
    data = await _ehraz_post(
        "https://ehraz.io/api/v1/match/card-with-national",
        {
            "cardNumber": formatted_card,
            "nationalCode": req.nationalCode,
            "birthDate": formatted_dob,
        },
        timeout_seconds=6,
    )
    return {"matched": bool(data.get("matched", False))}


@router.post("/verify/ehraz-mobile")
async def verify_mobile_with_ehraz(req: EhrazMobileRequest):
    data = await _ehraz_post(
        "https://ehraz.io/api/v1/match/national-with-mobile",
        {
            "nationalCode": req.nationalCode,
            "mobileNumber": req.mobileNumber,
        },
        timeout_seconds=6,
    )
    return {"matched": bool(data.get("matched", False))}


@router.post("/admin/login")
async def admin_login(req: AdminCredentials):
    role = _admin_role(req.username, req.password)
    if not role:
        raise HTTPException(status_code=401, detail="invalid_admin_credentials")
    _write_admin_log("admin_login", {"username": req.username, "role": role})
    return {"status": "success", "role": role}


@router.get("/admin/users")
async def admin_users(username: str, password: str):
    _require_roles(username, password, {"admin", "support", "viewer"})
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, first_name, last_name, phone_number, national_id, dob, bank_card_number, kyc_status, verification_level
               FROM users ORDER BY id DESC"""
        ).fetchall()
    return {"users": [dict(row) for row in rows]}


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: int, username: str, password: str):
    _require_roles(username, password, {"admin"})
    with get_db() as conn:
        conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    _write_admin_log("delete_user", {"user_id": user_id})
    return {"status": "deleted"}


@router.get("/admin/faqs")
async def admin_get_faqs(username: str, password: str):
    _require_roles(username, password, {"admin", "support", "viewer"})
    with get_db() as conn:
        rows = conn.execute("SELECT id, question, answer, created_at FROM faqs ORDER BY id DESC").fetchall()
    return {"faqs": [dict(row) for row in rows]}


@router.post("/admin/faqs")
async def admin_add_faq(req: FaqRequest):
    _require_roles(req.username, req.password, {"admin", "support"})
    with get_db() as conn:
        conn.execute("INSERT INTO faqs (question, answer) VALUES (?, ?)", (req.question, req.answer))
    _write_admin_log("add_faq", {"question": req.question})
    return {"status": "created"}


@router.delete("/admin/faqs/{faq_id}")
async def admin_delete_faq(faq_id: int, username: str, password: str):
    _require_roles(username, password, {"admin", "support"})
    with get_db() as conn:
        conn.execute("DELETE FROM faqs WHERE id = ?", (faq_id,))
    _write_admin_log("delete_faq", {"faq_id": faq_id})
    return {"status": "deleted"}


@router.get("/admin/logs")
async def admin_logs(username: str, password: str):
    _require_roles(username, password, {"admin", "support", "viewer"})
    with get_db() as conn:
        rows = conn.execute("SELECT id, action, details, created_at FROM admin_logs ORDER BY id DESC LIMIT 300").fetchall()
    return {"logs": [dict(row) for row in rows]}


@router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_user_password(user_id: int, req: AdminResetPasswordRequest):
    _require_roles(req.username, req.password, {"admin", "support"})
    with get_db() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="user_not_found")
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(req.new_password), user_id))
    _write_admin_log("reset_user_password", {"user_id": user_id})
    return {"status": "success"}


@router.post("/users/password-reset/start")
async def start_password_reset(req: PasswordResetStartRequest):
    if req.channel not in {"bot", "sms"}:
        raise HTTPException(status_code=400, detail="invalid_channel")

    normalized_phone = _normalize_iran_phone(req.phone_number)

    with get_db() as conn:
        # generic behavior: do not leak user existence
        user = conn.execute("SELECT id, phone_number FROM users WHERE phone_number = ?", (normalized_phone,)).fetchone()

        if user:
            recent_count = conn.execute(
                """SELECT COUNT(*) AS cnt FROM password_reset_tokens
                   WHERE phone_number = ? AND created_at >= datetime('now', '-5 minutes')""",
                (normalized_phone,),
            ).fetchone()["cnt"]
            if recent_count >= 5:
                logger.warning("password reset rate limited for %s", normalized_phone)
                return {"status": "sent"}

            code = str(random.randint(100000, 999999))
            expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
            conn.execute(
                "INSERT INTO password_reset_tokens (phone_number, channel, code, expires_at) VALUES (?, ?, ?, ?)",
                (normalized_phone, req.channel, code, expires_at),
            )
        else:
            code = None

    if req.channel == "sms" and user and code:
        ok, response_text = await _send_ghasedak_sms(
            normalized_phone,
            f"کد بازیابی رمز عبور: {code} (اعتبار: 10 دقیقه)",
        )
        _write_admin_log(
            "password_reset_sms",
            {"phone": normalized_phone, "success": ok, "provider_response": response_text[:300]},
        )
        
        # Return actual status instead of always "sent"
        if ok:
            return {"status": "sent", "message": "SMS sent successfully"}
        else:
            return {"status": "failed", "message": f"SMS failed: {response_text[:100]}"}

    # For bot channel the reset is handled inside Telegram bot conversation (/resetpassword)
    return {"status": "sent"}


@router.post("/users/password-reset/complete")
async def complete_password_reset(req: PasswordResetCompleteRequest):
    with get_db() as conn:
        token = conn.execute(
            """SELECT id, expires_at FROM password_reset_tokens
               WHERE phone_number = ? AND code = ? AND used = 0
               ORDER BY id DESC LIMIT 1""",
            (req.phone_number, req.code),
        ).fetchone()
        if not token:
            raise HTTPException(status_code=400, detail="invalid_code")
        if datetime.fromisoformat(token["expires_at"]) < datetime.utcnow():
            raise HTTPException(status_code=400, detail="expired_code")

        conn.execute(
            "UPDATE users SET password_hash = ? WHERE phone_number = ?",
            (hash_password(req.new_password), req.phone_number),
        )
        conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (token["id"],))

    return {"status": "success"}


@router.post("/admin/messages/send")
async def admin_send_message(req: AdminSendMessageRequest):
    _require_roles(req.username, req.password, {"admin", "support"})

    with get_db() as conn:
        if req.user_id:
            rows = conn.execute("SELECT id FROM users WHERE id = ?", (req.user_id,)).fetchall()
        else:
            rows = conn.execute("SELECT id FROM users ORDER BY id DESC").fetchall()

    sent = 0
    for row in rows:
        try:
            await _send_text(row["id"], req.message)
            sent += 1
        except Exception:
            continue

    _write_admin_log("admin_send_message", {"user_id": req.user_id, "sent": sent})
    return {"status": "success", "sent": sent}


@router.get("/admin/kyc-logs")
async def admin_kyc_logs(username: str, password: str):
    _require_roles(username, password, {"admin", "support", "viewer"})
    with get_db() as conn:
        ehraz_rows = conn.execute(
            """SELECT id, phone_number, national_id, endpoint, request_payload, response_payload, success, error_message, created_at
               FROM ehraz_logs ORDER BY id DESC LIMIT 500"""
        ).fetchall()
        sms_rows = conn.execute(
            """SELECT id, phone_number, provider, request_payload, response_payload, success, error_message, created_at
               FROM sms_logs ORDER BY id DESC LIMIT 500"""
        ).fetchall()
        kyc_verification_rows = conn.execute(
            """SELECT id, phone_number, national_id, action, details, created_at
               FROM kyc_verification_logs ORDER BY id DESC LIMIT 500"""
        ).fetchall()
    return {
        "ehraz_logs": [dict(r) for r in ehraz_rows], 
        "sms_logs": [dict(r) for r in sms_rows],
        "kyc_verification_logs": [dict(r) for r in kyc_verification_rows]
    }


@router.get("/admin/activity-logs")
async def admin_activity_logs(username: str, password: str):
    _require_roles(username, password, {"admin", "support", "viewer"})
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, user_id, phone_number, action, source, details, created_at
               FROM user_activity_logs ORDER BY id DESC LIMIT 1000"""
        ).fetchall()
    return {"logs": [dict(r) for r in rows]}


@router.get("/admin/rates")
async def admin_get_rates(username: str, password: str):
    _require_roles(username, password, {"admin", "support", "viewer"})
    return {"settings": get_rate_settings()}


@router.post("/admin/rates")
async def admin_update_rates(req: AdminRateSettingsUpdateRequest):
    _require_roles(req.username, req.password, {"admin", "support"})
    updated = update_rate_settings({
        "toman_to_tl_factor": req.toman_to_tl_factor,
        "tl_to_toman_factor": req.tl_to_toman_factor,
        "buy_usdt_factor": req.buy_usdt_factor,
        "sell_usdt_factor": req.sell_usdt_factor,
        "usdt_to_lira_factor": req.usdt_to_lira_factor,
        "lira_to_usdt_factor": req.lira_to_usdt_factor,
        "foreign_payment_factor": req.foreign_payment_factor,
    })
    _write_admin_log("update_rate_settings", updated)
    return {"status": "success", "settings": updated}

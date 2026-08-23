import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import aiohttp
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..admin_notify import now_text, send_admin_message
from ..api_settings import (
    get_ehraz_proxies,
    get_ehraz_test_mode,
    get_ehraz_token,
    get_ghasedak_api_key,
    get_ghasedak_line_number,
    get_ghasedak_proxy_format,
    get_ghasedak_proxy_pool,
    get_ghasedak_template,
)
from ..auth import create_access_token, get_current_user_id, get_jwt_secret, hash_password, verify_password
from ..database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

PERSIAN_NAME_RE = re.compile(r"^[\u0600-\u06ff\u200c\s]+$")
PASSWORD_LETTER_RE = re.compile(r"[A-Za-z]")
PASSWORD_DIGIT_RE = re.compile(r"\d")


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


class PasswordResetStartRequest(BaseModel):
    phone_number: str
    channel: str  # bot | sms


class PasswordResetCompleteRequest(BaseModel):
    phone_number: str
    code: str
    new_password: str


class RegisterCheckRequest(BaseModel):
    phone_number: str
    national_id: str


def _normalize_digits(value: str) -> str:
    translation = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return (value or "").translate(translation)


def _digits_only(value: str) -> str:
    return "".join(ch for ch in _normalize_digits(value) if ch.isdigit())


def _normalize_iran_phone(phone: str) -> str:
    digits = _digits_only(phone)
    if digits.startswith("0098"):
        return "0" + digits[4:]
    if digits.startswith("98"):
        return "0" + digits[2:]
    if digits.startswith("9") and len(digits) == 10:
        return "0" + digits
    return digits


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _validate_password(password: str) -> None:
    if len(password or "") < 8 or not PASSWORD_LETTER_RE.search(password) or not PASSWORD_DIGIT_RE.search(password):
        raise HTTPException(status_code=400, detail="weak_password")


def _validate_registration(req: RegisterRequest) -> RegisterRequest:
    req.first_name = _normalize_name(req.first_name)
    req.last_name = _normalize_name(req.last_name)
    req.phone_number = _normalize_iran_phone(req.phone_number)
    req.national_id = _digits_only(req.national_id)
    req.date_of_birth = _digits_only(req.date_of_birth)
    req.bank_card_number = _digits_only(req.bank_card_number)

    if not req.first_name or not PERSIAN_NAME_RE.fullmatch(req.first_name):
        raise HTTPException(status_code=400, detail="invalid_first_name")
    if not req.last_name or not PERSIAN_NAME_RE.fullmatch(req.last_name):
        raise HTTPException(status_code=400, detail="invalid_last_name")
    if not re.fullmatch(r"\d{10}", req.national_id) or len(set(req.national_id)) == 1:
        raise HTTPException(status_code=400, detail="invalid_national_id")
    if not re.fullmatch(r"\d{8}", req.date_of_birth):
        raise HTTPException(status_code=400, detail="invalid_date_of_birth")
    if not re.fullmatch(r"\d{16}", req.bank_card_number):
        raise HTTPException(status_code=400, detail="invalid_bank_card_number")
    if not re.fullmatch(r"09\d{9}", req.phone_number):
        raise HTTPException(status_code=400, detail="invalid_phone_number")
    _validate_password(req.password)
    return req


def _mask_phone(value: str | None) -> str:
    value = str(value or "")
    return f"{value[:4]}***{value[-4:]}" if len(value) >= 8 else "***"


def _mask_national_id(value: str | None) -> str:
    value = str(value or "")
    return f"***{value[-4:]}" if value else "***"


def _mask_card(value: str | None) -> str:
    value = str(value or "")
    return f"**** **** **** {value[-4:]}" if value else "****"


def _safe_ehraz_log_payload(payload: dict) -> dict:
    safe: dict[str, object] = {}
    if "mobileNumber" in payload:
        safe["mobileNumber"] = _mask_phone(str(payload.get("mobileNumber") or ""))
    if "nationalCode" in payload:
        safe["nationalCode"] = _mask_national_id(str(payload.get("nationalCode") or ""))
    if "cardNumber" in payload:
        safe["cardNumber"] = _mask_card(str(payload.get("cardNumber") or ""))
    if "birthDate" in payload:
        safe["birthDate"] = "********"
    return safe


def _safe_ehraz_response(data: object) -> dict:
    if not isinstance(data, dict):
        return {"received": bool(data)}
    safe = {}
    for key in ("matched", "isSuccess", "success", "message", "status", "code"):
        if key in data:
            safe[key] = data[key]
    return safe or {"received": True}


def _write_admin_log(action: str, details: dict | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            (action, json.dumps(details or {}, ensure_ascii=False)),
        )


def _log_user_activity(
    action: str,
    source: str,
    details: dict | None = None,
    user_id: int | None = None,
    phone_number: str | None = None,
) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO user_activity_logs (user_id, phone_number, action, source, details) VALUES (?, ?, ?, ?, ?)",
            (user_id, phone_number, action, source, json.dumps(details or {}, ensure_ascii=False)),
        )


def _write_ehraz_log(
    phone_number: str | None,
    national_id: str | None,
    endpoint: str,
    request_payload: dict,
    response_payload: dict,
    success: bool,
    error_message: str | None = None,
) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO ehraz_logs
               (phone_number, national_id, endpoint, request_payload, response_payload, success, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                _mask_phone(phone_number),
                _mask_national_id(national_id),
                endpoint,
                json.dumps(_safe_ehraz_log_payload(request_payload), ensure_ascii=False),
                json.dumps(response_payload, ensure_ascii=False),
                1 if success else 0,
                error_message,
            ),
        )


def _log_kyc_verification(action: str, phone_number: str, national_id: str, details: dict) -> None:
    safe_details = dict(details)
    safe_details.pop("ehraz_response", None)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO kyc_verification_logs
               (phone_number, national_id, action, details)
               VALUES (?, ?, ?, ?)""",
            (
                _mask_phone(phone_number),
                _mask_national_id(national_id),
                action,
                json.dumps(safe_details, ensure_ascii=False),
            ),
        )


def _write_sms_log(phone_number: str, provider_response: str, success: bool, error_message: str | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO sms_logs (phone_number, provider, request_payload, response_payload, success, error_message)
               VALUES (?, 'ghasedak', ?, ?, ?, ?)""",
            (
                _mask_phone(phone_number),
                json.dumps({"phone": _mask_phone(phone_number)}, ensure_ascii=False),
                provider_response[:500],
                1 if success else 0,
                error_message,
            ),
        )


def _user_dict(row) -> dict:
    return {
        "id": row["id"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "phone_number": row["phone_number"],
        "kyc_status": row["kyc_status"],
        "verification_level": row["verification_level"] if "verification_level" in row.keys() else 1,
        "national_id": row["national_id"] if "national_id" in row.keys() else None,
        "dob": row["dob"] if "dob" in row.keys() else None,
        "bank_card_number": row["bank_card_number"] if "bank_card_number" in row.keys() else None,
    }


def _check_conflicts(phone_number: str, national_id: str, bank_card_number: str | None = None) -> str | None:
    with get_db() as conn:
        if conn.execute("SELECT id FROM users WHERE phone_number = ?", (phone_number,)).fetchone():
            return "already_registered_phone"
        if conn.execute("SELECT id FROM users WHERE national_id = ?", (national_id,)).fetchone():
            return "already_registered_national_id"
        if bank_card_number and conn.execute(
            "SELECT id FROM users WHERE bank_card_number = ?", (bank_card_number,)
        ).fetchone():
            return "already_registered_card"
    return None


async def _ehraz_post(
    url: str,
    payload: dict,
    timeout_seconds: int = 6,
    phone_number: str | None = None,
    national_id: str | None = None,
) -> dict:
    token = get_ehraz_token()
    if not token:
        raise HTTPException(status_code=503, detail="ehraz_not_configured")

    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    attempts: list[str | None] = [None]
    proxies = get_ehraz_proxies()
    if proxies:
        sample_count = min(2, len(proxies))
        attempts.extend(secrets.SystemRandom().sample(proxies, sample_count))

    last_error = "all_attempts_failed"
    for proxy_url in attempts:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    proxy=proxy_url,
                    timeout=timeout,
                ) as response:
                    text = await response.text()
                    try:
                        data = json.loads(text) if text.strip() else {}
                    except json.JSONDecodeError:
                        data = {}
                    ok = response.status == 200 and isinstance(data, dict) and bool(data)
                    last_error = f"http_{response.status}" if response.status != 200 else "invalid_response"
                    _write_ehraz_log(
                        phone_number,
                        national_id,
                        url,
                        payload,
                        _safe_ehraz_response(data),
                        ok,
                        None if ok else last_error,
                    )
                    if ok:
                        return data
        except (aiohttp.ClientError, TimeoutError) as exc:
            last_error = type(exc).__name__
            _write_ehraz_log(
                phone_number,
                national_id,
                url,
                payload,
                {"network_error": type(exc).__name__},
                False,
                last_error,
            )

    raise HTTPException(status_code=503, detail="verification_service_unavailable")


async def _verify_registration_with_ehraz(req: RegisterRequest) -> None:
    if get_ehraz_test_mode():
        if os.getenv("ALLOW_KYC_TEST_MODE", "").strip().lower() not in {"1", "true", "yes"}:
            raise HTTPException(status_code=503, detail="kyc_test_mode_not_allowed")
        logger.warning("KYC test mode is enabled")
        return

    phone_match = await _ehraz_post(
        "https://ehraz.io/api/v1/match/national-with-mobile",
        {"nationalCode": req.national_id, "mobileNumber": req.phone_number},
        phone_number=req.phone_number,
        national_id=req.national_id,
    )
    if not bool(phone_match.get("matched", False)):
        raise HTTPException(status_code=400, detail="phone_national_mismatch")

    card_match = await _ehraz_post(
        "https://ehraz.io/api/v1/match/card-with-national",
        {
            "nationalCode": req.national_id,
            "birthDate": req.date_of_birth,
            "cardNumber": req.bank_card_number,
        },
        phone_number=req.phone_number,
        national_id=req.national_id,
    )
    if not bool(card_match.get("matched", False)):
        raise HTTPException(status_code=400, detail="card_national_mismatch")


async def _send_ghasedak_sms(phone_number: str, code: str) -> tuple[bool, str]:
    api_key = get_ghasedak_api_key()
    template_name = get_ghasedak_template()
    if not api_key:
        return (False, "missing_ghasedak_api_key")

    if template_name:
        url = "https://gateway.ghasedak.me/rest/api/v1/WebService/SendOtpWithParams"
        headers = {"accept": "text/plain", "ApiKey": api_key, "Content-Type": "application/json"}
        payload = {
            "receptors": [{"mobile": phone_number, "clientReferenceId": secrets.token_hex(8)}],
            "templateName": template_name,
            "param1": code,
            "isVoice": False,
            "udh": False,
        }
    else:
        url = "https://api.ghasedak.me/v2/sms/send/simple"
        headers = {"apikey": api_key, "Content-Type": "application/x-www-form-urlencoded"}
        payload = {"receptor": phone_number, "message": f"کد بازیابی رمز عبور: {code}"}
        line_number = get_ghasedak_line_number()
        if line_number:
            payload["linenumber"] = line_number

    proxy_format = get_ghasedak_proxy_format()
    proxy_start, proxy_end = get_ghasedak_proxy_pool()
    proxies: list[str | None] = [None]
    if proxy_format:
        proxies.extend(
            proxy_format.format(n=secrets.randbelow(proxy_end - proxy_start + 1) + proxy_start)
            for _ in range(2)
        )

    last_response = "sms_delivery_failed"
    for proxy_url in proxies:
        try:
            async with aiohttp.ClientSession() as session:
                request_kwargs = {
                    "headers": headers,
                    "proxy": proxy_url,
                    "timeout": aiohttp.ClientTimeout(total=15),
                }
                if template_name:
                    request_kwargs["json"] = payload
                else:
                    request_kwargs["data"] = payload
                async with session.post(url, **request_kwargs) as response:
                    body = await response.text()
                    ok = response.status == 200
                    last_response = f"http_{response.status}"
                    _write_sms_log(phone_number, last_response, ok, None if ok else last_response)
                    if ok:
                        return (True, body)
        except (aiohttp.ClientError, TimeoutError) as exc:
            last_response = type(exc).__name__
            _write_sms_log(phone_number, last_response, False, last_response)
    return (False, last_response)


def _reset_code_digest(phone_number: str, code: str) -> str:
    secret = get_jwt_secret().encode("utf-8")
    message = f"{phone_number}:{code}".encode("utf-8")
    return "hmac:" + hmac.new(secret, message, hashlib.sha256).hexdigest()


@router.post("/users/register/check")
async def check_register_conflicts(req: RegisterCheckRequest):
    phone = _normalize_iran_phone(req.phone_number)
    national_id = _digits_only(req.national_id)
    conflict = _check_conflicts(phone, national_id)
    return {
        "exists_phone": conflict == "already_registered_phone",
        "exists_national_id": conflict == "already_registered_national_id",
    }


@router.post("/users/register")
async def register_user(req: RegisterRequest):
    req = _validate_registration(req)
    conflict = _check_conflicts(req.phone_number, req.national_id, req.bank_card_number)
    if conflict:
        _log_user_activity("register_conflict", "miniapp", {"reason": conflict}, phone_number=_mask_phone(req.phone_number))
        raise HTTPException(status_code=409, detail=conflict)

    _log_kyc_verification("kyc_start", req.phone_number, req.national_id, {"step": "registration_attempt"})
    try:
        await _verify_registration_with_ehraz(req)
    except HTTPException as exc:
        _log_kyc_verification("kyc_failed", req.phone_number, req.national_id, {"detail": exc.detail})
        raise

    conflict = _check_conflicts(req.phone_number, req.national_id, req.bank_card_number)
    if conflict:
        raise HTTPException(status_code=409, detail=conflict)

    hashed = hash_password(req.password)
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO users
               (first_name, last_name, national_id, dob, bank_card_number,
                phone_number, password_hash, accepted_terms, kyc_status, verification_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'Approved', 1)""",
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
        user_id = int(cursor.lastrowid)

    _log_kyc_verification("kyc_success", req.phone_number, req.national_id, {"verification_level": 1})
    _log_user_activity("register_success", "miniapp", {"verification_level": 1}, user_id=user_id, phone_number=_mask_phone(req.phone_number))

    await send_admin_message(
        "📝 <b>ثبت نام جدید</b>\n"
        f"👤 نام: {html.escape(req.first_name)} {html.escape(req.last_name)}\n"
        f"📱 شماره: {html.escape(_mask_phone(req.phone_number))}\n"
        f"🆔 کد ملی: {html.escape(_mask_national_id(req.national_id))}\n"
        f"💳 کارت: {html.escape(_mask_card(req.bank_card_number))}\n"
        f"✅ سطح احراز: 1\n"
        f"⏰ زمان: {now_text()}"
    )
    return {"status": "success", "message": "User registered", "verification_level": 1}


@router.post("/users/login")
async def login_user(req: LoginRequest):
    phone_number = _normalize_iran_phone(req.phone_number)
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE phone_number = ?", (phone_number,)).fetchone()

    if not user or not user["password_hash"] or not verify_password(req.password, user["password_hash"]):
        _log_user_activity("login_failed", "miniapp", {"reason": "invalid_credentials"}, phone_number=_mask_phone(phone_number))
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"user_id": int(user["id"])})
    _log_user_activity(
        "login_success",
        "miniapp",
        {"kyc_status": user["kyc_status"]},
        user_id=int(user["id"]),
        phone_number=_mask_phone(phone_number),
    )
    return {"token": token, "user": _user_dict(user)}


@router.get("/users/me")
async def get_me(user_id: int = Depends(get_current_user_id)):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": _user_dict(user)}


@router.post("/verify/ehraz")
async def verify_with_ehraz(req: EhrazRequest):
    national_id = _digits_only(req.nationalCode)
    data = await _ehraz_post(
        "https://ehraz.io/api/v1/match/card-with-national",
        {
            "cardNumber": _digits_only(req.cardNumber),
            "nationalCode": national_id,
            "birthDate": _digits_only(req.birthDate),
        },
        national_id=national_id,
    )
    return {"matched": bool(data.get("matched", False))}


@router.post("/verify/ehraz-mobile")
async def verify_mobile_with_ehraz(req: EhrazMobileRequest):
    phone = _normalize_iran_phone(req.mobileNumber)
    national_id = _digits_only(req.nationalCode)
    data = await _ehraz_post(
        "https://ehraz.io/api/v1/match/national-with-mobile",
        {"nationalCode": national_id, "mobileNumber": phone},
        phone_number=phone,
        national_id=national_id,
    )
    return {"matched": bool(data.get("matched", False))}


@router.post("/users/password-reset/start")
async def start_password_reset(req: PasswordResetStartRequest):
    if req.channel not in {"bot", "sms"}:
        raise HTTPException(status_code=400, detail="invalid_channel")

    phone_number = _normalize_iran_phone(req.phone_number)
    code: str | None = None
    with get_db() as conn:
        user = conn.execute("SELECT id FROM users WHERE phone_number = ?", (phone_number,)).fetchone()
        if user:
            recent_count = conn.execute(
                """SELECT COUNT(*) AS cnt FROM password_reset_tokens
                   WHERE phone_number = ? AND created_at >= datetime('now', '-5 minutes')""",
                (phone_number,),
            ).fetchone()["cnt"]
            if recent_count < 5:
                code = f"{secrets.randbelow(900000) + 100000:06d}"
                expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
                conn.execute(
                    "INSERT INTO password_reset_tokens (phone_number, channel, code, expires_at) VALUES (?, ?, ?, ?)",
                    (phone_number, req.channel, _reset_code_digest(phone_number, code), expires_at),
                )

    if req.channel == "sms" and code:
        ok, _provider_response = await _send_ghasedak_sms(phone_number, code)
        if not ok:
            logger.warning("Password reset SMS delivery failed for %s", _mask_phone(phone_number))
    return {"status": "sent"}


@router.post("/users/password-reset/complete")
async def complete_password_reset(req: PasswordResetCompleteRequest):
    phone_number = _normalize_iran_phone(req.phone_number)
    _validate_password(req.new_password)
    code = _digits_only(req.code)
    digest = _reset_code_digest(phone_number, code)

    with get_db() as conn:
        token = conn.execute(
            """SELECT id, code, expires_at FROM password_reset_tokens
               WHERE phone_number = ? AND used = 0
               ORDER BY id DESC LIMIT 10""",
            (phone_number,),
        ).fetchall()
        matched = None
        for row in token:
            stored = str(row["code"] or "")
            if secrets.compare_digest(stored, digest) or secrets.compare_digest(stored, code):
                matched = row
                break
        if not matched:
            raise HTTPException(status_code=400, detail="invalid_code")
        expires_at = datetime.fromisoformat(matched["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="expired_code")

        conn.execute(
            "UPDATE users SET password_hash = ? WHERE phone_number = ?",
            (hash_password(req.new_password), phone_number),
        )
        conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (matched["id"],))

    _write_admin_log("user_password_reset", {"phone": _mask_phone(phone_number)})
    return {"status": "success"}

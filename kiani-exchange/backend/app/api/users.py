import aiohttp
import asyncio
import random
import logging
import os
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)
from ..database import get_db
from ..auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user_id,
)

EHRAZ_TOKEN = "5942b9d62abc20405dadfb2c0f546b669cf1471c"

# Telegram Bot Configuration
# Use the same token as in transactions.py for consistency
TELEGRAM_BOT_TOKEN = "8278787504:AAGU4jeKIYq4Kw_FNcgA-7_rb3H152aKxMU"
ADMIN_CHAT_ID = 2043363119

# List of proxy servers from your configuration
PROXY_LIST = [
    "45.159.53.29:7401",
    "107.181.142.146:5739",
    "147.136.85.66:5982",
    "193.160.78.239:5919",
    "104.250.207.125:6523",
    "173.245.88.77:5380",
    "107.181.143.171:6302",
    "45.38.84.162:7098",
    "67.227.1.26:6307",
    "92.113.1.107:5807",
    "64.137.92.43:6242",
    "67.227.37.170:5712",
    "191.96.173.42:6055",
    "104.143.252.167:5781",
    "45.141.81.25:6085",
    "168.199.145.4:6262",
    "45.38.111.198:6113",
    "31.58.23.166:5739",
    "45.150.178.246:6118",
    "206.206.71.86:5726",
    "67.227.37.52:5594",
    "92.112.155.70:7194",
    "104.239.97.191:5944",
    "2.57.30.125:7201",
    "104.238.14.125:6510",
    "104.239.44.190:6112",
    "184.174.126.51:6343",
    "136.0.189.140:6867",
    "168.199.145.55:6313",
    "2.57.31.223:6799",
    "67.227.42.206:6183",
    "194.39.32.247:6544",
    "140.233.166.169:7202",
    "31.59.21.101:6367",
    "64.137.37.38:6628",
    "102.212.88.222:6219",
    "104.233.13.184:6179",
    "104.252.28.134:6072",
    "136.0.118.200:6572",
    "80.96.71.105:5595",
    "193.187.114.215:6230",
    "45.38.84.253:7189",
    "93.118.38.64:6208",
    "206.206.64.140:6101",
    "64.137.57.98:6107",
    "104.252.193.112:6022",
    "185.15.178.101:5785",
    "104.253.81.21:5449",
    "148.135.188.5:7037",
    "31.57.90.143:5712",
    "45.147.187.3:6376",
    "45.150.23.199:6669",
    "145.223.40.236:5806",
    "155.254.38.123:5799",
    "46.203.45.196:6219",
    "185.171.255.30:6083",
    "46.203.79.27:6553",
    "45.159.54.195:7067",
    "92.112.227.32:6204",
    "82.29.229.112:6467",
    "23.129.254.13:5995",
    "67.227.113.72:5612",
    "67.227.113.15:5555",
    "92.112.238.65:6944",
    "82.22.210.225:8067",
    "45.61.97.253:6779",
    "23.236.170.178:9211",
    "104.252.193.75:5985",
    "82.29.229.65:6420",
    "23.229.110.120:8648",
    "82.24.236.86:7896",
    "31.58.24.163:6234",
    "45.14.83.8:7986",
    "82.23.225.200:8051",
    "204.217.245.155:6746",
    "82.27.214.241:6583",
    "82.23.221.29:6359",
    "45.131.94.82:6069",
    "103.101.88.202:5926",
    "82.21.245.103:6427",
    "161.123.33.185:6208",
    "23.95.255.75:6659",
    "98.159.38.158:6458",
    "45.39.4.13:5438",
    "82.24.249.60:5897",
    "136.0.189.227:6954",
    "82.21.245.189:6513",
    "206.232.103.58:6215",
    "23.27.196.222:6591",
    "104.143.226.126:5729",
    "82.25.247.17:6351",
    "92.112.235.4:6527",
    "82.23.204.82:6914",
    "23.27.210.154:6524",
    "104.238.38.24:6292",
    "216.173.72.20:6639",
    "23.229.125.113:5382",
    "82.29.245.125:6949",
    "50.114.99.138:6879",
    "50.114.99.125:6866"
]

def get_random_proxy():
    """Get a random proxy from the list"""
    proxy = random.choice(PROXY_LIST)
    return f"http://jjebraham:Amir1234@{proxy}"


async def send_telegram_notification(message: str):
    """Send notification to Telegram admin bot"""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or ADMIN_CHAT_ID == "YOUR_CHAT_ID_HERE":
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

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.ghasedak.me/v2/sms/send/simple",
                data=payload,
                headers=headers,
                timeout=10,
            ) as resp:
                body = await resp.text()
                logger.info("Ghasedak response status=%s body=%s", resp.status, body[:500])
                return (resp.status == 200, body)
    except Exception as exc:
        logger.error("Ghasedak send failed: %s", exc)
        return (False, str(exc))

async def _ehraz_post(url: str, payload: dict, timeout_seconds: int = 15):
    headers = {
        "Authorization": f"Bearer {EHRAZ_TOKEN}",
        "Content-Type": "application/json",
    }

    # Quick direct attempt first to reduce perceived latency.
    try:
        logger.info(f"EHRAZ direct attempt: {url}")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"EHRAZ direct success: {data}")
                    return data
                else:
                    logger.warning(f"EHRAZ direct failed with status: {resp.status}")
    except Exception as e:
        logger.warning(f"EHRAZ direct exception: {e}")

    # Fallback with proxy rotation.
    for attempt in range(3):  # Increased from 2 to 3 attempts
        proxy_url = get_random_proxy()
        try:
            logger.info(f"EHRAZ proxy attempt {attempt + 1}: {proxy_url}")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"EHRAZ proxy success: {data}")
                        return data
                    else:
                        logger.warning(f"EHRAZ proxy failed with status: {resp.status}")
        except Exception as e:
            logger.warning(f"EHRAZ proxy attempt {attempt + 1} exception: {e}")
            continue

    logger.error("All EHRAZ attempts failed")
    return {"matched": False}


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


@router.post("/users/register")
async def register_user(req: RegisterRequest):
    hashed = hash_password(req.password)

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE phone_number = ?",
            (req.phone_number,),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=409,
                detail="already_registered_phone",
            )

        existing_nid = conn.execute(
            "SELECT id FROM users WHERE national_id = ?",
            (req.national_id,),
        ).fetchone()
        if existing_nid:
            raise HTTPException(status_code=409, detail="already_registered_national_id")

        existing_card = conn.execute(
            "SELECT id FROM users WHERE bank_card_number = ?",
            (req.bank_card_number,),
        ).fetchone()
        if existing_card:
            raise HTTPException(status_code=409, detail="already_registered_card")

        conn.execute(
            """INSERT INTO users
               (first_name, last_name, national_id, dob,
                bank_card_number, phone_number, password_hash,
                accepted_terms, kyc_status, verification_level)
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

    return {"status": "success", "message": "User registered"}


@router.post("/users/login")
async def login_user(req: LoginRequest):
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
    logger.info(f"EHRAZ verification request: {req.nationalCode}, {req.cardNumber[:6]}...")
    
    # For testing: enable mock mode when EHRAZ is unreachable
    USE_MOCK_EHRAZ = True  # Set to False in production
    
    if USE_MOCK_EHRAZ:
        logger.info("Using mock EHRAZ mode for testing")
        
        # Normalize card number: remove spaces
        normalized_card = req.cardNumber.replace(" ", "")
        
        # Basic validation
        if len(req.nationalCode) == 10 and len(normalized_card) == 16:
            logger.info(f"Mock EHRAZ card validation passed: {req.nationalCode}, {normalized_card[:6]}...")
            return {"matched": True}
        else:
            logger.info(f"Mock EHRAZ card validation failed: nationalCode={len(req.nationalCode)} digits, card={len(normalized_card)} digits")
            return {"matched": False}
    
    data = await _ehraz_post(
        "https://ehraz.io/api/v1/match/card-with-national",
        {
            "cardNumber": req.cardNumber,
            "nationalCode": req.nationalCode,
            "birthDate": req.birthDate,
        },
        timeout_seconds=15,
    )
    result = bool(data.get("matched", False))
    logger.info(f"EHRAZ verification result: {result}")
    return {"matched": result}


@router.post("/verify/ehraz-mobile")
async def verify_mobile_with_ehraz(req: EhrazMobileRequest):
    logger.info(f"EHRAZ mobile verification request: {req.nationalCode}, {req.mobileNumber}")
    
    # For testing: enable mock mode when EHRAZ is unreachable
    USE_MOCK_EHRAZ = True  # Set to False in production
    
    if USE_MOCK_EHRAZ:
        logger.info("Using mock EHRAZ mode for mobile verification testing")
        
        # Normalize mobile number: remove +, spaces, dashes
        normalized_mobile = req.mobileNumber.replace('+', '').replace(' ', '').replace('-', '')
        
        # Handle different formats:
        # - 09123456789 (11 digits with 0)
        # - 9123456789 (10 digits without 0)
        # - 989123456789 (12 digits with country code)
        
        # Check if it's a valid Iranian mobile number
        is_valid_iran_mobile = False
        
        # Format 1: 09123456789 (11 digits, starts with 09)
        if normalized_mobile.startswith('09') and len(normalized_mobile) == 11:
            is_valid_iran_mobile = True
        # Format 2: 9123456789 (10 digits, starts with 9) - add leading 0
        elif normalized_mobile.startswith('9') and len(normalized_mobile) == 10:
            is_valid_iran_mobile = True
        # Format 3: 989123456789 (12 digits, starts with 98) - remove country code
        elif normalized_mobile.startswith('98') and len(normalized_mobile) == 12:
            is_valid_iran_mobile = True
        
        # Basic validation
        if len(req.nationalCode) == 10 and is_valid_iran_mobile:
            logger.info(f"Mock EHRAZ mobile validation passed: {req.nationalCode}, {req.mobileNumber}")
            return {"matched": True}
        else:
            logger.info(f"Mock EHRAZ mobile validation failed: nationalCode={len(req.nationalCode)} digits, mobile={req.mobileNumber}")
            return {"matched": False}
    
    data = await _ehraz_post(
        "https://ehraz.io/api/v1/match/national-with-mobile",
        {
            "nationalCode": req.nationalCode,
            "mobileNumber": req.mobileNumber,
        },
        timeout_seconds=15,
    )
    result = bool(data.get("matched", False))
    logger.info(f"EHRAZ mobile verification result: {result}")
    return {"matched": result}


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

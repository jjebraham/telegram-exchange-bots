import aiohttp
import asyncio
import random
import logging
import os
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
    }


@router.post("/users/register")
async def register_user(req: RegisterRequest):
    hashed = hash_password(req.password)

    with get_db() as conn:
        # Check if phone number already exists
        existing = conn.execute(
            "SELECT id FROM users WHERE phone_number = ?",
            (req.phone_number,),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="این شماره موبایل قبلاً ثبت شده است",
            )

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
    # For testing, you can set USE_MOCK_EHRAZ = True
    # In production, set USE_MOCK_EHRAZ = False
    USE_MOCK_EHRAZ = False
    
    if USE_MOCK_EHRAZ:
        # Mock response for testing
        # In a real scenario, you might want to do some basic validation
        # For example, check if the national ID is 10 digits, etc.
        return {"matched": True}
    
    # Send verification attempt notification
    notification_message = (
        "🔍 <b>تلاش احراز هویت</b>\n"
        f"🆔 کدملی: {req.nationalCode}\n"
        f"💳 کارت: {req.cardNumber}\n"
        f"📅 تاریخ: {req.birthDate}\n"
        f"⏰ زمان: {asyncio.get_event_loop().time()}"
    )
    await send_telegram_notification(notification_message)
    
    # Real EHRAZ API call with proxy rotation
    url = "https://ehraz.io/api/v1/match/card-with-national"
    headers = {
        "Authorization": f"Token {EHRAZ_TOKEN}",
        "Content-Type": "application/json",
    }
    
    # Try with multiple proxies
    max_retries = 5  # Increased retries
    tried_proxies = set()
    
    for attempt in range(max_retries):
        # Get a proxy we haven't tried yet
        available_proxies = [p for p in PROXY_LIST if p not in tried_proxies]
        if not available_proxies:
            # Reset and try all proxies again
            tried_proxies.clear()
            available_proxies = PROXY_LIST.copy()
            
        proxy = random.choice(available_proxies)
        proxy_url = f"http://jjebraham:Amir1234@{proxy}"
        tried_proxies.add(proxy)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={
                        "cardNumber": req.cardNumber,
                        "nationalCode": req.nationalCode,
                        "birthDate": req.birthDate,
                    },
                    headers=headers,
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=10),  # Reduced timeout
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {"matched": data.get("matched", False)}
                    else:
                        logger.warning(f"EHRAZ API returned status {resp.status} with proxy {proxy}")
                        continue
        except asyncio.TimeoutError:
            logger.warning(f"Timeout with proxy {proxy} (attempt {attempt + 1})")
            continue
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} with proxy {proxy} failed: {e}")
            continue
    
    # If all retries failed, return False
    logger.error("All proxy attempts failed for EHRAZ verification")
    return {"matched": False}

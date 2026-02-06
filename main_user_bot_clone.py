#!/usr/bin/env python3

import logging
import sqlite3
import asyncio
import random
import re
import os
import time
import aiohttp
import io
from datetime import datetime
import traceback

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
    InlineKeyboardButton, ReplyKeyboardRemove, FSInputFile, BufferedInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup

###############################################################################
# CONFIGURATION
###############################################################################
MAIN_BOT_TOKEN   = "8509657640:AAG4gNsyvG0xt5ePoFXraBlMUb6hIrWmaWE"
ADMIN_BOT_TOKEN  = "8278787504:AAGU4jeKIYq4Kw_FNcgA-7_rb3H152aKxMU"
ADMIN_CHAT_ID    = 2043363119
PROXY_URL        = "http://jjebraham-25:Amir1234@p.webshare.io:80"

# WALLEX CONFIG
WALLEX_API_KEY  = "15064|7tVDd4NDBYmATAe4lWTUQSTzj0v7ceTELEv6u6zG"
WALLEX_BASE_URL = "https://api.wallex.ir/v1"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("debug.log", encoding="utf-8")
    ]
)
logging.debug("Debug logging is enabled for main bot.")

bot       = Bot(token=MAIN_BOT_TOKEN, proxy=PROXY_URL)
admin_bot = Bot(token=ADMIN_BOT_TOKEN, proxy=PROXY_URL)
storage   = MemoryStorage()
dp        = Dispatcher(storage=storage)

###############################################################################
# ADMIN LOGGING MIDDLEWARE
###############################################################################
async def log_to_admin(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}]\n{message}"
    admin_url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendMessage"
    params = {
        "chat_id": ADMIN_CHAT_ID,
        "text": formatted,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(admin_url, json=params, timeout=10) as resp:
                if resp.status != 200:
                    logging.error(f"Admin log failed: {await resp.text()}")
    except Exception as e:
        logging.error(f"Failed to log to admin: {e}")
        traceback.print_exc()

class AdminLogMiddleware:
    async def __call__(self, handler, event, data):
        try:
            if isinstance(event, types.Message) and event.from_user:
                uid = event.from_user.id
                uname = f"{event.from_user.first_name} {event.from_user.last_name or ''}"
                if event.text and event.text.startswith('/'):
                    action = f"executed command: {event.text}"
                elif event.text:
                    action = f"sent message: {event.text}"
                elif event.photo:
                    action = "sent a photo"
                elif event.document:
                    action = "sent a document"
                elif event.contact:
                    action = "shared a contact"
                else:
                    action = "performed an interaction"
                await log_to_admin(f"👤 User: {uid} ({uname})\n🔍 Action: {action}")
                result = await handler(event, data)
                if isinstance(result, types.Message) and result.text:
                    await log_to_admin(f"🤖 Bot response: {result.text}")
                return result

            if isinstance(event, types.CallbackQuery) and event.from_user:
                uid = event.from_user.id
                uname = f"{event.from_user.first_name} {event.from_user.last_name or ''}"
                await log_to_admin(f"👤 User: {uid} ({uname})\n🔍 Action: pressed {event.data}")
                result = await handler(event, data)
                if isinstance(result, types.Message) and result.text:
                    await log_to_admin(f"🤖 Bot response: {result.text}")
                return result

            return await handler(event, data)
        except Exception as e:
            logging.error(f"Error in AdminLogMiddleware: {e}")
            traceback.print_exc()
            return await handler(event, data)

###############################################################################
# DATABASE FUNCTIONS
###############################################################################
def get_db_connection():
    conn = sqlite3.connect("users.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                phone_number TEXT UNIQUE,
                national_id TEXT,
                dob TEXT,
                bank_card_number TEXT,
                accepted_terms INTEGER,
                front_id TEXT,
                back_id TEXT,
                kyc_status TEXT DEFAULT 'Pending',
                reference_code TEXT,
                kyc_notified INT DEFAULT 0
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS bank_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_number TEXT,
                UNIQUE(user_id, card_number),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.commit()
    logging.debug("Database initialized for main bot.")

###############################################################################
# PRICE CACHE CLASS (with Wallex fallback)
###############################################################################
class PriceCache:
    def __init__(self):
        self.usdt_irr      = None
        self.usdt_irr_time = 0
        self.usdt_try      = None
        self.usdt_try_time = 0
        self.fetch_interval = 600  # seconds

    async def fetch_usdt_irr(self) -> float:
        # 1) Primary: flask proxy
        primary_url = "https://flask-9l1dbb.chbk.app/proxy/usdt-to-rls"
        logging.debug(f"Fetching USDT-IRR (primary): {primary_url}")
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(primary_url, proxy=PROXY_URL, timeout=10) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    rate = data.get("usdt_to_rls")
                    if rate:
                        logging.debug(f"Primary USDT-IRR: {rate}")
                        return float(rate)
                    raise ValueError("no usdt_to_rls in primary response")
        except Exception as e:
            logging.warning(f"Primary USDT-IRR failed: {e}")

        # 2) Fallback: Wallex API (Corrected Logic)
        logging.info("Falling back to Wallex API")
        try:
            headers = {"X-API-KEY": WALLEX_API_KEY, "User-Agent": "Mozilla/5.0"}
            # Use the CORRECT endpoint: /markets
            async with aiohttp.ClientSession() as sess:
                async with sess.get(f"{WALLEX_BASE_URL}/markets",
                                      headers=headers,
                                      proxy=PROXY_URL,
                                      timeout=10) as resp2:
                    resp2.raise_for_status()
                    body = await resp2.json()

                    # New logic to parse the response from the /markets endpoint
                    symbols = body.get("result", {}).get("symbols", {})
                    usdt_market_data = symbols.get("USDTTMN")

                    if not usdt_market_data:
                        raise ValueError("USDTTMN market data not found in Wallex /markets response")

                    price_tmn = float(usdt_market_data["stats"]["lastPrice"])
                    logging.debug(f"Wallex USDTTMN price (Toman): {price_tmn}")

                    if price_tmn > 0:
                        return price_tmn * 10  # Convert Toman to Rial
                    else:
                        raise ValueError("Wallex returned an invalid price (zero or less)")
        except Exception as e2:
            logging.error(f"Wallex fallback failed: {e2}")
            traceback.print_exc()

        logging.error("All USDT-IRR sources failed")
        return None

    async def fetch_usdt_try(self) -> float:
        btcturk_url = "https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY"
        logging.debug(f"Fetching USDT-TRY: {btcturk_url}")
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(btcturk_url, proxy=PROXY_URL, timeout=10) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    arr = data.get("data", [])
                    if arr:
                        lastp = arr[0].get("last")
                        return float(lastp)
        except Exception as e:
            logging.error(f"Exception fetching USDT-TRY: {e}")
        return None

    async def get_usdt_irr(self) -> float:
        now = time.time()
        if self.usdt_irr is None or (now - self.usdt_irr_time) > self.fetch_interval:
            r = await self.fetch_usdt_irr()
            if r:
                self.usdt_irr      = r
                self.usdt_irr_time = now
            else:
                self.usdt_irr = None
        return self.usdt_irr

    async def get_usdt_try(self) -> float:
        now = time.time()
        if self.usdt_try is None or (now - self.usdt_try_time) > self.fetch_interval:
            r = await self.fetch_usdt_try()
            if r:
                self.usdt_try      = r
                self.usdt_try_time = now
            else:
                self.usdt_try = None
        return self.usdt_try

price_cache = PriceCache()

###############################################################################
# EHRAZ ATTEMPTS AND API CALL
###############################################################################
ehraz_attempts = {}
def get_today_str():
    return datetime.now().strftime("%Y%m%d")

def check_ehraz_attempts(user_id: int) -> bool:
    today = get_today_str()
    rec = ehraz_attempts.get(user_id)
    if not rec:
        ehraz_attempts[user_id] = {"date": today, "count": 0}
        logging.debug(f"EHRAZ: New record for user {user_id}")
        return True
    if rec["date"] != today:
        ehraz_attempts[user_id] = {"date": today, "count": 0}
        logging.debug(f"EHRAZ: Reset record for user {user_id} for a new day")
        return True
    logging.debug(f"EHRAZ: User {user_id} has {rec['count']} attempts today")
    return rec["count"] < 10

def increment_ehraz(user_id: int):
    today = get_today_str()
    rec = ehraz_attempts.get(user_id, {"date": today, "count": 0})
    if rec["date"] != today:
        rec = {"date": today, "count": 0}
    rec["count"] += 1
    ehraz_attempts[user_id] = rec
    logging.debug(f"EHRAZ: Incremented attempts for user {user_id} to {rec['count']}")

async def match_card_with_national(card_number: str, national_id: str, dob: str) -> bool:
    url = "https://ehraz.io/api/v1/match/card-with-national"
    headers = {
        "Authorization": "Token 5942b9d62abc20405dadfb2c0f546b669cf1471c",
        "Content-Type": "application/json"
    }
    proxy_url_for_sync = PROXY_URL
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={
                "cardNumber": card_number,
                "nationalCode": national_id,
                "birthDate": dob
            }, headers=headers, proxy=proxy_url_for_sync, timeout=20) as resp:
                text = await resp.text()
                logging.debug(f"EHRAZ API response (status {resp.status}): {text}")
                if resp.status != 200:
                    return False
                data = await resp.json()
                return bool(data.get("matched", False))
    except Exception as e:
        logging.error(f"Error calling EHRAZ: {e}")
        return False

###############################################################################
# HELPER FUNCTIONS
###############################################################################
def convert_persian_digits_to_english(text: str) -> str:
    mapping = {
        '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
        '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
        '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
        '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'
    }
    return ''.join(mapping.get(c, c) for c in text)

def parse_jalali_dob(input_text: str) -> str:
    txt = convert_persian_digits_to_english(input_text).replace("/", "").strip()
    if not (txt.isdigit() and len(txt) == 8 and txt.startswith("13")):
        return None
    mm, dd = int(txt[4:6]), int(txt[6:8])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    return txt

def is_valid_national_id(nid: str) -> bool:
    eng = convert_persian_digits_to_english(nid.strip())
    return bool(re.match(r"^\d{10}$", eng)) and len(set(eng)) > 1

def is_valid_card_number(card_number: str) -> bool:
    eng = convert_persian_digits_to_english(card_number)
    clean = re.sub(r"\s+", "", eng)
    return len(clean) == 16 and clean.isdigit()

def round_to_nearest_10(x: float) -> int:
    return int(round(x / 10.0) * 10)

###############################################################################
# FSM STATES
###############################################################################
class RegisterState(StatesGroup):
    first_name = State()
    last_name = State()
    phone_number = State()
    national_id = State()
    dob = State()
    bank_card_number = State()
    front_id = State()
    back_id = State()

class RegistrationReview(StatesGroup):
    waiting = State()
    edit_nid = State()
    edit_dob = State()
    edit_card = State()

class BankCardState(StatesGroup):
    adding = State()

class PaymentState(StatesGroup):
    website = State()
    site_account = State()
    site_password = State()
    amount = State()
    details = State()

class LoginState(StatesGroup):
    phone = State()

class ReuploadState(StatesGroup):
    front_id = State()
    back_id = State()

###############################################################################
# MENUS - CORRECTED AND STANDARDIZED
###############################################################################
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="ثبت نام ✍️"), KeyboardButton(text="🚪 ورود")],
        [KeyboardButton(text="نرخ خرید لیر از ما\n🇮🇷 ➡️ 🇹🇷"), KeyboardButton(text="نرخ فروش لیر به ما\n🇹🇷 ➡️ 🇮🇷")],
        [KeyboardButton(text="نرخ خرید تتر از ما\n🇮🇷 ➡️ 💰"), KeyboardButton(text="نرخ فروش تتر به ما\n💰 ➡️ 🇮🇷")],
        [KeyboardButton(text="نرخ تبدیل لیر به تتر\n🇹🇷 ➡️ 💰"), KeyboardButton(text="نرخ تبدیل تتر به لیر\n💰 ➡️ 🇹🇷")],
        [KeyboardButton(text="قوانین و مقررات"), KeyboardButton(text="سوالات متداول")],
        [KeyboardButton(text="تماس با ما ☎️")]
    ],
    resize_keyboard=True
)

user_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="کارت های بانکی من 💳")],
        [KeyboardButton(text="خرید لیر از ما\n🇮🇷 ➡️ 🇹🇷"), KeyboardButton(text="فروش لیر به ما\n🇹🇷 ➡️ 🇮🇷")],
        [KeyboardButton(text="خرید تتر از ما\n🇮🇷 ➡️ 💰"), KeyboardButton(text="فروش تتر به ما\n💰 ➡️ 🇮🇷")],
        [KeyboardButton(text="تبدیل لیر به تتر\n🇹🇷 ➡️ 💰"), KeyboardButton(text="تبدیل تتر به لیر\n💰 ➡️ 🇹🇷")],
        [KeyboardButton(text="پرداخت در سایت های خارجی 🛍️🛒💳")],
        [KeyboardButton(text="خروج از حساب کاربری 📤")]
    ],
    resize_keyboard=True
)

###############################################################################
# BACKGROUND LOOP: CHECK KYC STATUS
###############################################################################
async def check_kyc_loop():
    while True:
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT id, kyc_status
                    FROM users
                    WHERE (kyc_status IN ('Approved','Rejected'))
                      AND (coalesce(kyc_notified,0)=0)
                """)
                rows = c.fetchall()
            for r in rows:
                user_id = r["id"]
                st = r["kyc_status"]
                if st == "Approved":
                    try:
                        await bot.send_message(user_id, "احراز هویت شما با موفقیت تکمیل شد✅", reply_markup=user_menu)
                        with get_db_connection() as conn_update:
                            c2 = conn_update.cursor()
                            c2.execute("UPDATE users SET kyc_notified=1 WHERE id=?", (user_id,))
                            conn_update.commit()
                    except Exception as e:
                        logging.error(f"Failed to inform user {user_id}: {e}")
                elif st == "Rejected":
                    try:
                        await bot.send_message(user_id, "❌ مدارک شما تایید نشد\nلطفاً تصویر پشت و روی کارت ملی تان را دوباره ارسال کنید.")
                        with get_db_connection() as conn_update:
                            c2 = conn_update.cursor()
                            c2.execute("UPDATE users SET kyc_notified=1, kyc_status='Pending' WHERE id=?", (user_id,))
                            conn_update.commit()
                        await bot.send_message(user_id, "لطفاً ابتدا تصویر روی کارت ملی تان را دوباره آپلود کنید.")
                    except Exception as e:
                        logging.error(f"Failed to message user {user_id} about rejection: {e}")
        except Exception as e:
            logging.error(f"check_kyc_loop error: {e}")
        await asyncio.sleep(10)

###############################################################################
# REUPLOAD FLOW FOR REJECTED USERS
###############################################################################
@dp.message(ReuploadState.front_id, F.photo)
async def reup_front_photo(message: types.Message, state: FSMContext):
    fid = message.photo[-1].file_id
    await state.update_data(front_id=fid)
    await message.answer("تصویر روی کارت ملی دریافت شد. ✅")
    await state.set_state(ReuploadState.back_id)
    await message.answer("لطفاً تصویر پشت کارت ملی خود را آپلود کنید 🪪")

@dp.message(ReuploadState.front_id)
async def reup_front_nonphoto(message: types.Message, state: FSMContext):
    await message.answer("لطفاً عکس روی کارت ملی را ارسال کنید (فقط photo).")

@dp.message(ReuploadState.back_id, F.photo)
async def reup_back_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bid = message.photo[-1].file_id
    if bid == data.get("front_id"):
        await message.answer("تصویر پشت و روی کارت ملی یکسان است! لطفاً تصویر پشت را مجدد ارسال کنید.")
        return
    await state.update_data(back_id=bid)
    await finish_registration_info(message, state)

@dp.message(ReuploadState.back_id)
async def reup_back_nonphoto(message: types.Message, state: FSMContext):
    await message.answer("لطفاً عکس پشت کارت ملی را ارسال کنید (فقط photo).")

###############################################################################
# REGISTRATION FLOW AND CORRECTIONS
###############################################################################
async def ask_for_corrections(message: types.Message, state: FSMContext):
    data = await state.get_data()
    nid = data.get("national_id", "")
    dob = data.get("dob", "")
    card = data.get("bank_card_number", "")
    dob_formatted = f"{dob[0:4]}/{dob[4:6]}/{dob[6:8]}" if len(dob)==8 else dob
    msg_text = (
        "اطلاعات کارت با کد ملی همخوانی ندارد.\n"
        f"کد ملی وارد شده: {nid}\n"
        f"تاریخ تولد وارد شده: {dob_formatted}\n"
        f"کارت بانکی وارد شده: {card}\n\n"
        "لطفاً اطلاعات وارد شده را بررسی کنید و در صورت اشتباه بودن هر کدام با زدن دکمه‌های پایین اصلاح بفرمایید."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="اصلاح کد ملی", callback_data="edit_nid"),
        InlineKeyboardButton(text="اصلاح تاریخ تولد", callback_data="edit_dob"),
        InlineKeyboardButton(text="اصلاح کارت بانکی", callback_data="edit_card")
    ]])
    await message.answer(msg_text, reply_markup=kb)

@dp.callback_query(F.data=="edit_nid")
async def edit_nid_cb(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer("لطفاً کد ملی جدید را وارد کنید (10 رقم):")
    await state.set_state(RegistrationReview.edit_nid)

@dp.message(RegistrationReview.edit_nid)
async def correct_nid(message: types.Message, state: FSMContext):
    new_nid = convert_persian_digits_to_english(message.text.strip())
    if not is_valid_national_id(new_nid):
        await message.answer("کد ملی نامعتبر است. لطفاً 10 رقم وارد کنید.")
        return
    await state.update_data(national_id=new_nid)
    await re_check_ehraz(message, state)

@dp.callback_query(F.data=="edit_dob")
async def edit_dob_cb(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer("لطفاً تاریخ تولد را اصلاح کنید (مثال: 1365/06/26 یا 13650626):")
    await state.set_state(RegistrationReview.edit_dob)

@dp.message(RegistrationReview.edit_dob)
async def correct_dob(message: types.Message, state: FSMContext):
    parsed = parse_jalali_dob(message.text)
    if not parsed:
        await message.answer("تاریخ تولد نامعتبر است.")
        return
    await state.update_data(dob=parsed)
    await re_check_ehraz(message, state)

@dp.callback_query(F.data=="edit_card")
async def edit_card_cb(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer("لطفاً شماره کارت بانکی صحیح را وارد کنید (16 رقم):")
    await state.set_state(RegistrationReview.edit_card)

@dp.message(RegistrationReview.edit_card)
async def correct_card(message: types.Message, state: FSMContext):
    new_card = re.sub(r"\s+", "", convert_persian_digits_to_english(message.text.strip()))
    if not is_valid_card_number(new_card):
        await message.answer("کارت نامعتبر است. لطفاً 16 رقم وارد کنید.")
        return
    await state.update_data(bank_card_number=new_card)
    await re_check_ehraz(message, state)

async def re_check_ehraz(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    nid, dob, cnum = data["national_id"], data["dob"], data["bank_card_number"]
    if not check_ehraz_attempts(user_id):
        await message.answer("بیش از 10 بار تلاش کرده‌اید. لطفاً با پشتیبانی تماس بگیرید:\nhttps://t.me/TL905411603664")
        await state.clear()
        return
    increment_ehraz(user_id)
    matched = await match_card_with_national(cnum, nid, dob)
    if matched:
        await message.answer("شما مرحله اول احراز هویت را با موفقیت تکمیل کردید✅\nلطفاً تصویر روی کارت ملی تان را آپلود کنید🪪")
        await state.set_state(RegisterState.front_id)
    else:
        await ask_for_corrections(message, state)

###############################################################################
# FINISH REGISTRATION & ADMIN NOTIFICATION
###############################################################################
async def finish_registration_info(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    old_info = {}
    with get_db_connection() as conn:
        c = conn.cursor()
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row:
            old_info = dict(row)

    first_name = data.get("first_name") or old_info.get("first_name", "")
    last_name  = data.get("last_name") or old_info.get("last_name", "")
    phone      = data.get("phone_number") or old_info.get("phone_number", "")
    nid        = data.get("national_id") or old_info.get("national_id", "")
    dob        = data.get("dob") or old_info.get("dob", "")
    bank_card  = data.get("bank_card_number") or old_info.get("bank_card_number", "")
    front_id   = data.get("front_id") or old_info.get("front_id", "")
    back_id    = data.get("back_id") or old_info.get("back_id", "")

    ref_code = str(random.randint(1000, 9999))
    uid_gen  = datetime.now().strftime("%Y%m%d%H%M%S") + str(random.randint(10, 99))

    await message.answer(f"مدارک شما ارسال شد✅\nشماره پیگیری: {ref_code}\nUser ID: {uid_gen}\nمنتظر تایید باشید ⏳", reply_markup=main_menu)

    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            exists = c.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
            if not exists:
                c.execute("""
                    INSERT INTO users (id, first_name, last_name, phone_number, national_id, dob, bank_card_number, accepted_terms, front_id, back_id, kyc_status, reference_code, kyc_notified)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'Pending', ?, 0)
                """, (user_id, first_name, last_name, phone, nid, dob, bank_card, front_id, back_id, ref_code))
            else:
                c.execute("""
                    UPDATE users
                    SET first_name=?, last_name=?, phone_number=?, national_id=?, dob=?, bank_card_number=?, front_id=?, back_id=?, kyc_status='Pending', reference_code=?, kyc_notified=0
                    WHERE id=?
                """, (first_name, last_name, phone, nid, dob, bank_card, front_id, back_id, ref_code, user_id))
            conn.commit()
    except Exception as e:
        logging.error(f"DB error: {e}")

    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="تایید", callback_data=f"approve_{ref_code}"),
             InlineKeyboardButton(text="رد", callback_data=f"reject_{ref_code}")]
        ])
        admin_text = (
            f"New Registration Received:\n"
            f"User ID: {user_id}\n"
            f"UID Generated: {uid_gen}\n"
            f"Name: {first_name} {last_name}\n"
            f"Phone: {phone}\n"
            f"National ID: {nid}\n"
            f"DOB: {dob}\n"
            f"Bank Card: {bank_card}\n"
            f"Reference Code: {ref_code}"
        )
        await admin_bot.send_message(ADMIN_CHAT_ID, admin_text, reply_markup=kb)
        if front_id:
            fi = await bot.get_file(front_id)
            dl_front = await bot.download_file(fi.file_path)
            buff_front = BufferedInputFile(dl_front.read(), filename="front.jpg")
            await admin_bot.send_photo(ADMIN_CHAT_ID, buff_front, caption="Front ID")
        if back_id:
            fi2 = await bot.get_file(back_id)
            dl_back = await bot.download_file(fi2.file_path)
            buff_back = BufferedInputFile(dl_back.read(), filename="back.jpg")
            await admin_bot.send_photo(ADMIN_CHAT_ID, buff_back, caption="Back ID")
    except Exception as e:
        logging.error(f"Error sending admin notification: {e}")

    await state.clear()

###############################################################################
# /start COMMAND HANDLER
###############################################################################
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("به صرافی کیانی خوش آمدید.\nبرای شروع ثبت نام کنید یا وارد حساب کاربری شوید.", reply_markup=main_menu)

###############################################################################
# REGISTRATION FLOW
###############################################################################
@dp.message(F.text=="ثبت نام ✍️")
async def register_start(message: types.Message, state: FSMContext):
    await state.set_state(RegisterState.first_name)
    await message.answer("لطفاً نام خود را وارد کنید:", reply_markup=ReplyKeyboardRemove())

@dp.message(RegisterState.first_name)
async def register_fname(message: types.Message, state: FSMContext):
    fn = message.text.strip()
    if not fn:
        await message.answer("نام خالی است.")
        return
    await state.update_data(first_name=fn)
    await state.set_state(RegisterState.last_name)
    await message.answer("لطفاً نام خانوادگی خود را وارد کنید:")

@dp.message(RegisterState.last_name)
async def register_lname(message: types.Message, state: FSMContext):
    ln = message.text.strip()
    if not ln:
        await message.answer("نام خانوادگی خالی است.")
        return
    await state.update_data(last_name=ln)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="ارسال شماره تلفن من", request_contact=True)]],
                             resize_keyboard=True, one_time_keyboard=True)
    await state.set_state(RegisterState.phone_number)
    await message.answer("لطفاً شماره تلفن همراه خود (شماره ایران) را ارسال کنید:", reply_markup=kb)

@dp.message(RegisterState.phone_number, F.contact)
async def register_phone_ok(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number
    if phone.startswith("0098"):
        phone = "+" + phone[2:]
    elif phone.startswith("98") and not phone.startswith("+"):
        phone = "+" + phone
    if not phone.startswith("+98"):
        await message.answer("لطفاً از شماره تلفن ایران استفاده کنید.", reply_markup=main_menu)
        await state.clear()
        return
    with get_db_connection() as conn:
        c = conn.cursor()
        r = c.execute("SELECT id FROM users WHERE phone_number=?", (phone,)).fetchone()
        if r:
            await message.answer("شما قبلاً حساب کاربری دارید. لطفاً از بخش ورود استفاده کنید.", reply_markup=main_menu)
            await state.clear()
            return
    await state.update_data(phone_number=phone)
    await state.set_state(RegisterState.national_id)
    await message.answer("لطفاً شماره ملی خود را وارد کنید (10 رقم):", reply_markup=ReplyKeyboardRemove())

@dp.message(RegisterState.phone_number)
async def register_phone_wrong(message: types.Message, state: FSMContext):
    pdf_path = "telegramnumber.pdf"
    txt = ("لطفا شماره تلفن تان را به صورت دستی وارد نکنید. با فشردن دکمه پایین، آن را با ربات به اشتراک بگذارید.")
    await message.answer(txt)
    if os.path.exists(pdf_path):
        await message.answer_document(FSInputFile(pdf_path))

@dp.message(RegisterState.national_id)
async def register_nid(message: types.Message, state: FSMContext):
    nid = convert_persian_digits_to_english(message.text.strip())
    if not is_valid_national_id(nid):
        await message.answer("شماره ملی نامعتبر است.")
        return
    await state.update_data(national_id=nid)
    await state.set_state(RegisterState.dob)
    await message.answer("لطفاً تاریخ تولدتان را به شمسی وارد کنید (مثال: 1365/06/26 یا 13650626):")

@dp.message(RegisterState.dob)
async def register_dob(message: types.Message, state: FSMContext):
    parsed = parse_jalali_dob(message.text)
    if not parsed:
        await message.answer("تاریخ تولد نامعتبر است.")
        return
    await state.update_data(dob=parsed)
    await state.set_state(RegisterState.bank_card_number)
    await message.answer("لطفاً شماره کارت بانکی خود را وارد کنید (16 رقم):")

@dp.message(RegisterState.bank_card_number)
async def register_card(message: types.Message, state: FSMContext):
    cnum = re.sub(r"\s+", "", convert_persian_digits_to_english(message.text.strip()))
    if not is_valid_card_number(cnum):
        await message.answer("کارت نامعتبر است. لطفاً دوباره 16 رقم کارت را وارد کنید.")
        return

    await state.update_data(bank_card_number=cnum)
    data = await state.get_data()
    nid, dob = data.get("national_id"), data.get("dob")
    user_id = message.from_user.id

    if not check_ehraz_attempts(user_id):
        await message.answer("بیش از 10 بار تلاش کرده‌اید. لطفاً با پشتیبانی تماس بگیرید:\nhttps://t.me/TL905411603664")
        await state.clear()
        return

    increment_ehraz(user_id)
    matched = await match_card_with_national(cnum, nid, dob)

    if not matched:
        await state.set_state(RegistrationReview.waiting)
        await ask_for_corrections(message, state)
        return

    await message.answer("شما مرحله اول احراز هویت را با موفقیت تکمیل کردید✅\nلطفاً تصویر روی کارت ملی تان را آپلود کنید🪪")
    await state.set_state(RegisterState.front_id)

@dp.message(RegisterState.front_id, F.photo)
async def front_photo_reg(message: types.Message, state: FSMContext):
    fid = message.photo[-1].file_id
    await state.update_data(front_id=fid)
    await message.answer("تصویر روی کارت ملی دریافت شد ✅")
    await state.set_state(RegisterState.back_id)
    await message.answer("لطفاً تصویر پشت کارت ملی خود را آپلود کنید 🪪")

@dp.message(RegisterState.back_id, F.photo)
async def back_photo_reg(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if message.photo[-1].file_id == data.get("front_id"):
        await message.answer("تصویر پشت و روی کارت ملی یکسان است.")
        return
    await state.update_data(back_id=message.photo[-1].file_id)
    await finish_registration_info(message, state)

###############################################################################
# LOGIN FLOW
###############################################################################
@dp.message(F.text=="🚪 ورود")
async def cmd_login(message: types.Message, state: FSMContext):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="ارسال شماره تلفن من", request_contact=True)]],
                             resize_keyboard=True, one_time_keyboard=True)
    await state.set_state(LoginState.phone)
    await message.answer("شماره تلفن را ارسال کنید:", reply_markup=kb)

@dp.message(LoginState.phone, F.contact)
async def do_login_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number
    if phone.startswith("0098"):
        phone = "+" + phone[2:]
    elif phone.startswith("98") and not phone.startswith("+"):
        phone = "+" + phone
    if not phone.startswith("+98"):
        await message.answer("شماره ایران...", reply_markup=main_menu)
        await state.clear()
        return

    with get_db_connection() as conn:
        c = conn.cursor()
        r = c.execute("SELECT id, kyc_status, first_name, last_name, bank_card_number FROM users WHERE phone_number=?", (phone,)).fetchone()

    if not r:
        await message.answer("شما ثبت نام نکرده‌اید...", reply_markup=main_menu)
        await state.clear()
        return

    user_id, st, uf, ul, uc = r['id'], r['kyc_status'], r['first_name'], r['last_name'], r['bank_card_number']

    if st=="Pending":
        await message.answer("احراز هویت شما در حال بررسی است...", reply_markup=main_menu)
    elif st=="Rejected":
        await message.answer("مدارک شما رد شده است. لطفاً برای ارسال مجدد مدارک با پشتیبانی در ارتباط باشید.", reply_markup=main_menu)
    elif st=="Approved":
        cards = []
        if uc:
            cards.append(uc)
        with get_db_connection() as conn:
            c2 = conn.cursor()
            extras = c2.execute("SELECT card_number FROM bank_cards WHERE user_id=?", (user_id,)).fetchall()
        for ex in extras:
            cards.append(ex["card_number"])

        text = f"ورود موفقیت‌آمیز\n{uf} {ul} خوش آمدید.\n"
        if cards:
            text += "کارت‌ها:\n" + "\n".join(f"✅ {cd}" for cd in cards)
        await message.answer(text, reply_markup=user_menu)
    else:
        await message.answer("وضعیت نامشخص...", reply_markup=main_menu)

    await state.clear()

@dp.message(LoginState.phone)
async def do_login_phone_wrong(message: types.Message, state: FSMContext):
    await message.answer("لطفاً شماره تلفن تان را به صورت دستی وارد نکنید. با فشردن دکمه پایین، آن را با ربات به اشتراک بگذارید")
    pdf_path = "telegramnumber.pdf"
    if os.path.exists(pdf_path):
        await message.answer_document(FSInputFile(pdf_path))

###############################################################################
# USER MENU: کارت‌های بانکی
###############################################################################
@dp.message(F.text=="کارت های بانکی من ��")
async def my_cards(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    with get_db_connection() as conn:
        c = conn.cursor()
        row = c.execute("SELECT bank_card_number FROM users WHERE id=?", (user_id,)).fetchone()
        extras = c.execute("SELECT card_number FROM bank_cards WHERE user_id=?", (user_id,)).fetchall()

    cards = []
    if row and row["bank_card_number"]:
        cards.append(row["bank_card_number"])
    for ex in extras:
        cards.append(ex["card_number"])

    msg_txt = (
        "✴️ برای خرید یا فروش حتما کارتی که از آن واریز می‌کنید یا می‌خواهید به آن ریال دریافت کنید باید ثبت شده باشد.\n"
        "💳 لطفاً کارت بانکی تان را ثبت بفرمایید.\n\n"
        "❗️در نظر داشته باشید فقط ثبت کارت‌های به نام خودتان امکانپذیر است.❗️\n\n"
    )
    if cards:
        msg_txt += "کارت تایید شده:\n" + "\n".join(f"✅ {cd}" for cd in cards)
    else:
        msg_txt += "هیچ کارت بانکی ثبت نشده"

    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="اضافه کردن کارت جدید")],
        [KeyboardButton(text="بازگشت به منوی کاربری")]
    ], resize_keyboard=True)
    await message.answer(msg_txt, reply_markup=kb)

@dp.message(F.text=="اضافه کردن کارت جدید")
async def add_card_start(message: types.Message, state: FSMContext):
    await state.set_state(BankCardState.adding)
    await message.answer("لطفاً 16 رقم کارت بانکی جدید را وارد کنید:", reply_markup=ReplyKeyboardRemove())

@dp.message(BankCardState.adding)
async def add_card_process(message: types.Message, state: FSMContext):
    card = re.sub(r"\s+", "", convert_persian_digits_to_english(message.text.strip()))
    if not is_valid_card_number(card):
        await message.answer("کارت وارد شده اشتباه است یا به نام شما نیست.\nلطفاً 16 رقم کارت بانکی خود را با دقت وارد کنید.")
        return

    user_id = message.from_user.id
    with get_db_connection() as conn:
        c = conn.cursor()
        row = c.execute("SELECT national_id, dob FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        await message.answer("شما ثبت نام نکرده‌اید.")
        await state.clear()
        return

    nid, dob = row["national_id"], row["dob"]
    if not check_ehraz_attempts(user_id):
        await message.answer("بیش از 10 بار تلاش کرده‌اید. لطفاً با پشتیبانی تماس بگیرید:\nhttps://t.me/TL905411603664")
        await state.clear()
        return

    increment_ehraz(user_id)
    matched = await match_card_with_national(card, nid, dob)
    if not matched:
        await message.answer("اطلاعات کارتی که وارد کردید یا اشتباه است یا با کد ملی شما تطابق ندارد\nلطفاً دوباره سعی کنید و در نظر داشته باشید فقط کارت به نام خودتان قابل قبول است")
        return

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO bank_cards (user_id, card_number) VALUES (?, ?)", (user_id, card))
        conn.commit()

    await message.answer("کارت شما با موفقیت ثبت شد✅", reply_markup=user_menu)
    try:
        await admin_bot.send_message(ADMIN_CHAT_ID, f"New card added by user {user_id}: {card}")
    except Exception as e:
        logging.error(f"Failed to notify admin of new card addition: {e}")

    await state.clear()
    await my_cards(message, state)

@dp.message(F.text=="بازگشت به منوی کاربری")
async def back_to_user_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("بازگشت...", reply_markup=user_menu)

###############################################################################
# USER & MAIN MENU HANDLERS (Corrected and Standardized)
###############################################################################

# --- Lira Handlers ---
@dp.message(F.text == "خرید لیر از ما\n🇮🇷 ➡️ 🇹🇷")
async def buy_lira_user(message: types.Message):
    wait1 = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_irr = await price_cache.get_usdt_irr()
    usdt_try = await price_cache.get_usdt_try()
    await wait1.delete()
    if not usdt_irr or not usdt_try:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    eff_toman = usdt_irr / 10
    rate = round_to_nearest_10((eff_toman / usdt_try) * 1.02)
    await message.answer(f"هر واحد لیر ترکیه 🇹🇷 برای خرید: **{rate:,} تومان** می‌باشد.", parse_mode="Markdown")
    pdf_path = "buy_lira.pdf"
    if os.path.exists(pdf_path):
        await message.answer_document(FSInputFile(pdf_path), caption="لطفاً فرم را پر کنید و برای پشتیبانی ارسال کنید: @TL905411603664")

@dp.message(F.text == "نرخ خرید لیر از ما\n🇮🇷 ➡️ 🇹🇷")
async def main_menu_buy_lira_rate(message: types.Message):
    wait1 = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_irr = await price_cache.get_usdt_irr()
    usdt_try = await price_cache.get_usdt_try()
    await wait1.delete()
    if not usdt_irr or not usdt_try:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    eff_toman = usdt_irr / 10
    rate = round_to_nearest_10((eff_toman / usdt_try) * 1.02)
    await message.answer(f"هر واحد لیر ترکیه 🇹🇷 برای خرید: **{rate:,} تومان** می‌باشد.", parse_mode="Markdown")

@dp.message(F.text == "فروش لیر به ما\n🇹🇷 ➡️ 🇮🇷")
async def sell_lira_user(message: types.Message):
    wait1 = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_irr = await price_cache.get_usdt_irr()
    usdt_try = await price_cache.get_usdt_try()
    await wait1.delete()
    if not usdt_irr or not usdt_try:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    eff_toman = usdt_irr / 10
    rate = round_to_nearest_10((eff_toman / usdt_try) * 0.97)
    await message.answer(f"هر واحد لیر ترکیه ��🇷 برای فروش: **{rate:,} تومان** می‌باشد.", parse_mode="Markdown")
    pdf_path = "sell_lira.pdf"
    if os.path.exists(pdf_path):
        await message.answer_document(FSInputFile(pdf_path), caption="لطفاً فرم را پر کنید و برای پشتیبانی ارسال کنید: @TL905411603664")

@dp.message(F.text == "نرخ فروش لیر به ما\n🇹🇷 ➡️ 🇮🇷")
async def main_menu_sell_lira_rate(message: types.Message):
    wait1 = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_irr = await price_cache.get_usdt_irr()
    usdt_try = await price_cache.get_usdt_try()
    await wait1.delete()
    if not usdt_irr or not usdt_try:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    eff_toman = usdt_irr / 10
    rate = round_to_nearest_10((eff_toman / usdt_try) * 0.97)
    await message.answer(f"هر واحد لیر ترکیه 🇹🇷 برای فروش: **{rate:,} تومان** می‌باشد.", parse_mode="Markdown")


# --- Tether Handlers ---
@dp.message(F.text == "خرید تتر از ما\n🇮🇷 ➡️ 💰")
async def buy_tether_user(message: types.Message):
    wait = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_irr = await price_cache.get_usdt_irr()
    await wait.delete()
    if not usdt_irr:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    eff_toman = usdt_irr / 10
    rate = round_to_nearest_10(eff_toman * 1.01)
    await message.answer(f"هر واحد تتر 💰 برای خرید: **{rate:,} تومان** می‌باشد.", parse_mode="Markdown")
    await message.answer("لطفاً وجه را از حساب خودتان واریز کنید و قبل از واریز هماهنگ کنید.")
    await message.answer(
        "بانک سامان\n\n"
        "شماره حساب:\n`871-888-1072049-1`\n\n"
        "شبا:\n`IR110560087188801072049001`\n\n"
        "کارت:\n`6219861074320283`\n\n"
        "هادی کیانی راد",
        parse_mode="Markdown"
    )
    await message.answer("اولین واریز 72 ساعت نزد ما به امانت می‌ماند و پس از آن به حساب شما واریز می‌شود.")

@dp.message(F.text == "نرخ خرید تتر از ما\n🇮🇷 ➡️ 💰")
async def main_menu_buy_tether_rate(message: types.Message):
    wait = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_irr = await price_cache.get_usdt_irr()
    await wait.delete()
    if not usdt_irr:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    eff_toman = usdt_irr / 10
    rate = round_to_nearest_10(eff_toman * 1.01)
    await message.answer(f"هر واحد تتر 💰 برای خرید: **{rate:,} تومان** می‌باشد.", parse_mode="Markdown")

@dp.message(F.text == "فروش تتر به ما\n💰 ➡️ 🇮🇷")
async def sell_tether_user(message: types.Message):
    wait = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_irr = await price_cache.get_usdt_irr()
    await wait.delete()
    if not usdt_irr:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    eff_toman = usdt_irr / 10
    rate = round_to_nearest_10(eff_toman * 0.99)
    await message.answer(f"هر واحد تتر 💰 برای فروش: **{rate:,} تومان** می‌باشد.", parse_mode="Markdown")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="TRC20", callback_data="trc20_selltether"),
        InlineKeyboardButton(text="BEP20", callback_data="bep20_selltether")
    ]])
    await message.answer("شبکه را انتخاب کنید:", reply_markup=kb)

@dp.message(F.text == "نرخ فروش تتر به ما\n💰 ➡️ 🇮🇷")
async def main_menu_sell_tether_rate(message: types.Message):
    wait = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_irr = await price_cache.get_usdt_irr()
    await wait.delete()
    if not usdt_irr:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    eff_toman = usdt_irr / 10
    rate = round_to_nearest_10(eff_toman * 0.99)
    await message.answer(f"هر واحد تتر 💰 برای فروش: **{rate:,} تومان** می‌باشد.", parse_mode="Markdown")


@dp.callback_query(F.data=="trc20_selltether")
async def trc20_selltether_cb(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.answer("TRC20 Address:\n`TPLCxx4ji927DF2HVJm66qw19BaUXxR21B`", parse_mode="Markdown")

@dp.callback_query(F.data=="bep20_selltether")
async def bep20_selltether_cb(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.answer("BEP20 Address:\n`0x2c31c59fCCEBCCc7d9B9a299911A0bdC0CD40558`", parse_mode="Markdown")


# --- Lira/Tether Conversion Handlers (FINAL FIX) ---
@dp.message(F.text.startswith("تبدیل لیر به تتر"))
async def lira_to_tether_user(message: types.Message):
    wait1 = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_try = await price_cache.get_usdt_try()
    await wait1.delete()
    if not usdt_try:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    rate = usdt_try * 1.02
    await message.answer(f"هر **1 تتر** = **{rate:.2f} لیر**\n(نرخ تبدیل لیر به تتر)", parse_mode="Markdown")
    await message.answer("لطفاً قبل از واریز هماهنگ کنید.")
    await message.answer(
        "Bank name: VAKIF BANK\n"
        "Account: `TR63 0001 5001 5800 7323 7387 86`\n"
        "Holder: HADI KIANIRAD",
        parse_mode="Markdown"
    )
    await message.answer("بدون توضیحات واریز کنید و رسید را ارسال کنید: @TL905411603664")

@dp.message(F.text.startswith("نرخ تبدیل لیر به تتر"))
async def main_menu_lira_to_tether_rate(message: types.Message):
    wait1 = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_try = await price_cache.get_usdt_try()
    await wait1.delete()
    if not usdt_try:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    rate = usdt_try * 1.02
    await message.answer(f"هر **1 تتر** = **{rate:.2f} لیر**\n(نرخ تبدیل لیر به تتر)", parse_mode="Markdown")


@dp.message(F.text.startswith("تبدیل تتر به لیر"))
async def tether_to_lira_user(message: types.Message):
    wait = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_try = await price_cache.get_usdt_try()
    await wait.delete()
    if not usdt_try:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    rate = usdt_try * 0.98
    await message.answer(f"هر **1 تتر** = **{rate:.2f} لیر**\n(نرخ تبدیل تتر به لیر)", parse_mode="Markdown")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="TRC20", callback_data="trc20_tether2lira"),
        InlineKeyboardButton(text="BEP20", callback_data="bep20_tether2lira")
    ]])
    await message.answer("شبکه را انتخاب کنید:", reply_markup=kb)

@dp.message(F.text.startswith("نرخ تبدیل تتر به لیر"))
async def main_menu_tether_to_lira_rate(message: types.Message):
    wait = await message.answer("در حال دریافت آخرین نرخ... ⏳")
    usdt_try = await price_cache.get_usdt_try()
    await wait.delete()
    if not usdt_try:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    rate = usdt_try * 0.98
    await message.answer(f"هر **1 تتر** = **{rate:.2f} لیر**\n(نرخ تبدیل تتر به لیر)", parse_mode="Markdown")


@dp.callback_query(F.data=="trc20_tether2lira")
async def trc20_t2l_cb(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.answer("TRC20 Address:\n`TPLCxx4ji927DF2HVJm66qw19BaUXxR21B`", parse_mode="Markdown")

@dp.callback_query(F.data=="bep20_tether2lira")
async def bep20_t2l_cb(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.answer("BEP20 Address:\n`0x2c31c59fCCEBCCc7d9B9a299911A0bdC0CD40558`", parse_mode="Markdown")


###############################################################################
# USER MENU: پرداخت در سایت های خارجی
###############################################################################
@dp.message(F.text=="پرداخت در سایت های خارجی 🛍️🛒💳")
async def payment_site_start(message: types.Message, state: FSMContext):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="بازگشت به منوی کاربری")]], resize_keyboard=True)
    await state.set_state(PaymentState.website)
    await message.answer(
        "لطفاً اطلاعات زیر را ارسال کنید:\n"
        "✅ آدرس سایت\n✅ یوزرنیم و پسورد\n✅ مبلغ دلاری\n✅ توضیحات اشتراک\n"
        "⚠️ رمزهای دومرحله‌ای را موقتاً غیرفعال کنید.\n\n"
        "آدرس سایت را وارد کنید:",
        reply_markup=kb
    )

@dp.message(F.text == "بازگشت به منوی کاربری", PaymentState)
async def payment_site_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("بازگشت به منوی کاربری", reply_markup=user_menu)

@dp.message(PaymentState.website)
async def payment_website(message: types.Message, state: FSMContext):
    site = message.text.strip()
    if '.' not in site:
        await message.answer("Please enter a valid website address (must contain '.').")
        return
    await state.update_data(website=site)
    await state.set_state(PaymentState.site_account)
    await message.answer("نام کاربری یا ایمیل را وارد کنید:")

@dp.message(PaymentState.site_account)
async def payment_site_account(message: types.Message, state: FSMContext):
    acc = message.text.strip()
    await state.update_data(site_account=acc)
    await state.set_state(PaymentState.site_password)
    await message.answer("رمز عبور را وارد کنید (رمز را موقتاً تغییر دهید و بعد از پرداخت دوباره تغییر دهید):")

@dp.message(PaymentState.site_password)
async def payment_site_pwd(message: types.Message, state: FSMContext):
    pwd = message.text.strip()
    await state.update_data(site_password=pwd)
    await state.set_state(PaymentState.amount)
    await message.answer("لطفاً مبلغ دلاری را وارد کنید (فقط عدد):")

@dp.message(PaymentState.amount)
async def payment_amt(message: types.Message, state: FSMContext):
    amt = convert_persian_digits_to_english(message.text.strip())
    if not amt.isdigit():
        await message.answer("مبلغ اشتباه است. فقط عدد وارد کنید.")
        return
    await state.update_data(amount=amt)
    await state.set_state(PaymentState.details)
    await message.answer("توضیحات اشتراک را وارد کنید:")

@dp.message(PaymentState.details)
async def payment_done(message: types.Message, state: FSMContext):
    detail = message.text.strip()
    data = await state.get_data()
    user_id = message.from_user.id
    website  = data.get("website", "")
    account  = data.get("site_account", "")
    pwd      = data.get("site_password", "")
    amt      = data.get("amount", "")
    with get_db_connection() as conn:
        c = conn.cursor()
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        await message.answer("ابتدا ثبت نام کنید /start", reply_markup=main_menu)
        await state.clear()
        return
    fn = row["first_name"] or ""
    ln = row["last_name"] or ""
    phone = row["phone_number"] or ""
    nid = row["national_id"] or ""
    ref_pay = "PAY_" + str(random.randint(1000,9999))
    text_info = (
        f"Payment Request:\n"
        f"User ID: {user_id}\n"
        f"Name: {fn} {ln}\n"
        f"Phone: {phone}\n"
        f"National ID: {nid}\n\n"
        f"Website: {website}\n"
        f"Account: {account}\n"
        f"Password: {pwd}\n"
        f"Amount(USD): {amt}\n"
        f"Details: {detail}\n"
        f"Ref: {ref_pay}"
    )
    try:
        await admin_bot.send_message(ADMIN_CHAT_ID, text_info)
    except Exception as e:
        logging.error(f"Failed to send Payment req to admin: {e}")
    await message.answer("✅ درخواست شما ثبت شد.", reply_markup=user_menu)
    await state.clear()

###############################################################################
# USER MENU: خروج از حساب کاربری
###############################################################################
@dp.message(F.text=="خروج از حساب کاربری 📤")
async def logout_user(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("شما خارج شدید. ✅", reply_markup=main_menu)

###############################################################################
# قوانین و مقررات (ارسال خط به خط)
###############################################################################
@dp.message(F.text=="قوانین و مقررات")
async def rules_cmd(message: types.Message):
    rules = [
        "1️⃣⭕️🔟 کاربران موظفند قبل از ثبت‌نام تمامی مفاد این تعهدنامه را مطالعه نموده و در صورت پذیرش اقدام به ثبت نام نمایند.",
        "2️⃣⭕️🔟 کاربران صرافی کیانی می‌پذیرند که کلیه‌ی فعالیت‌های آن‌ها تحت قوانین جمهوری اسلامی ایران و ترکیه بوده و هیچ گونه فعالیتی خارج از این چارچوب انجام نخواهند داد۔",
        "3️⃣⭕️🔟 در اولین تراکنش، صرافی کیانی مجاز است مبلغ را به مدت 72 ساعت نگه‌دارد تا از عدم وجود فعالیت مشکوک اطمینان حاصل کند۔",
        "4️⃣⭕️🔟 احراز هویت برای استفاده از خدمات صرافی کیانی ضروری است. در صورت هرگونه تخلف، مسئولیت به عهده فرد متخلف خواهد بود۔",
        "5️⃣⭕️🔟 صرافی کیانی خود را ملزم به حفظ اطلاعات شخصی کاربران می‌داند۔",
        "6️⃣⭕️🔟 در صورت نیاز به تشخیص مدیریت جهت احراز هویت، با تیم پشتیبانی تماس تصویری داشته باشید۔",
        "7️⃣⭕️🔟 صرافی کیانی متعهد به حفظ دارایی‌های کاربران با بالاترین استانداردهای امنیتی است۔",
        "8️⃣⭕️🔟 کاربران موظفند از خدمات صرافی تنها برای خود استفاده نمایند۔",
        "9️⃣⭕️🔟 در صورت برداشت ارزهای دیجیتال، مسئولیت ارائه آدرس صحیح کیف پول بر عهده کاربر است۔",
        "🔟⭕️🔟 واریز وجه ریالی به حساب کاربران در ایران در اولین سیکل پایا انجام می‌شود. در روزهای تعطیل، واریزها به اولین روز کاری موکول می‌شود۔",
        "⛔️ در صورت تشخیص تقلب، صرافی حق گزارش به مراجع قضایی را دارد۔",
        "⚠️ کاربران موظفند هویت خود را به درستی تأیید کنند."
    ]
    for line in rules:
        await message.answer(line)
        await asyncio.sleep(0.5)

###############################################################################
# سوالات متداول (FAQ)
###############################################################################
FAQ_QUESTIONS = [
    ("چطور ثبت نام کنم؟",
     "روی دکمه ثبت نام بزنید و با وارد کردن نام، نام خانوادگی، کد ملی، تاریخ تولد، به اشتراک گذاری شماره تلگرام ایرانی و شماره کارت بانکی به نام خودتان ثبت نام کنید."),
    ("کدام شماره تلفن قابل قبول است؟",
     "تنها شماره تلفن ایران مورد قبول است و فقط با به اشتراک گذاری شماره تلفن تلگرام تان می‌توانید ثبت نام را تکمیل کنید."),
    ("چطور کارت جدید ثبت کنم؟",
     "پس از ورود به حساب کاربری، از منوی 'کارت های بانکی من' روی گزینه 'اضافه کردن کارت جدید' بزنید و 16 رقم کارت بانکی خود را وارد کنید (فقط کارت بانکی به نام خودتان مورد قبول است)."),
    ("واریز های ریالی چقدر زمان می‌برد؟",
     "واریز های ریالی در اولین سیکل پایا به حساب بانکی شما در ایران واریز می‌شود.\nسیکل‌های پایا: ساعت 04:00، 11:00، 14:00، 19:00.\nپرداخت‌های تعطیلی به اولین روز کاری موکول می‌شود.\nمثلاً اگر سفارش شما ساعت 15 ثبت شود، واریز ریالی ساعت 19 انجام می‌شود (معمولاً یک ساعت بعد یعنی ساعت 20 به حساب مشتری واریز می‌شود)."),
    ("در صورت خرید تتر واریز تتر چقدر زمان می‌برد؟",
     "اگر اولین واریز ریالی شما به حساب ما باشد، به دستور پلیس فتا مبلغ واریزی شما به مدت 72 ساعت نزد ما به امانت باقی می‌ماند سپس به آدرس تتری که معرفی کرده‌اید واریز می‌شود.\nاز خرید دوم به بعد ظرف یک ساعت تراکنش انجام می‌شود."),
    ("آیا برای خرید لیر یا تتر می‌توانم از حساب شخص دیگری (مادر، پدر، همسر، برادر، خواهر، دوست) استفاده کنم؟",
     "خیر، شما تنها از حساب بانکی به نام خودتان می‌توانید واریز ریالی داشته باشید.\nبرای واریز از حساب شخص ثالث، او باید در ربات ثبت نام و احراز هویت کند.")
]
FAQ_7_BUTTON = "سوال دیگری دارید؟"

@dp.message(F.text=="سوالات متداول")
async def faqs_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for i, (q, _) in enumerate(FAQ_QUESTIONS, start=1):
        kb.inline_keyboard.append([InlineKeyboardButton(text=q, callback_data=f"faq_{i}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text=FAQ_7_BUTTON, callback_data="faq_other")])
    await message.answer("سوالات متداول:", reply_markup=kb)

@dp.callback_query(F.data.startswith("faq_"))
async def faqs_answer(cb: types.CallbackQuery):
    await cb.answer()
    parts = cb.data.split("_")
    if parts[1] == "other":
        await cb.message.answer("اگر سوال دیگری دارید لطفاً به این آیدی پیام بدهید:\nhttps://t.me/TL905411603664")
        return
    idx = int(parts[1]) - 1
    if 0 <= idx < len(FAQ_QUESTIONS):
        q, ans = FAQ_QUESTIONS[idx]
        await cb.message.answer(f"پاسخ:\n{ans}")

###############################################################################
# تماس با ما
###############################################################################
@dp.message(F.text=="تماس با ما ☎️")
async def contact_us_cmd(message: types.Message):
    text = (
        "دفتر ما در استانبول:\n"
        "☎️ +90 212 294 33 34\n"
        "📱 +90 539 290 56 86\n"
        "�� +90 541 160 36 64\n"
        "📱 +98 912 195 82 96\n"
        "Whatsapp: https://wa.me/905392905686\n"
        "https://wa.me/905411603664\n"
        "آدرس: https://maps.app.goo.gl/zEUA7XGR5XDRzG3q8"
    )
    await message.answer(text)

###############################################################################
# BOT STARTUP
###############################################################################
async def main():
    init_db()
    logging.debug("Starting MAIN user bot…")
    dp.message.middleware.register(AdminLogMiddleware())
    dp.callback_query.middleware.register(AdminLogMiddleware())
    
    # Start background tasks
    kyc_task = asyncio.create_task(check_kyc_loop())
    
    await log_to_admin("🔄 Bot restarted and logging initialized")
    
    # Start polling
    try:
        await dp.start_polling(bot)
    finally:
        # This part will be reached on graceful shutdown (e.g., Ctrl+C)
        kyc_task.cancel()
        await asyncio.gather(kyc_task, return_exceptions=True)
        logging.info("Bot and background tasks stopped gracefully.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot shutdown requested!")

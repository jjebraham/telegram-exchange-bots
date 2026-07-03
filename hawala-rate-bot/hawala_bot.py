#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone Kiani Exchange hawala-rate Telegram poster."""

from __future__ import annotations

import fcntl
import logging
import logging.handlers
import os
import signal
import sqlite3
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Dict, Optional, Union

import ccxt
import jdatetime
import pytz
import requests
import telebot
import telebot.apihelper
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

BASE_DIR = os.environ.get(
    "HAWALA_BASE_DIR",
    "/home/kianirad2020/hawala-rate-bot",
)
LOG_PATH = os.path.join(BASE_DIR, "hawala_activity.log")
DB_PATH = os.path.join(BASE_DIR, "hawala_state.db")
LOCK_PATH = os.path.join(BASE_DIR, "hawala_bot.lock")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL_ID_RAW = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
ADMIN_CHAT_ID_RAW = os.environ.get("ADMIN_CHAT_ID", "").strip()
PROXY_URL = os.environ.get("PROXY_URL", "").strip()
WALLEX_API_KEY = os.environ.get("WALLEX_API_KEY", "").strip()
CURRENCYAPI_KEYS = [
    key.strip()
    for key in os.environ.get("CURRENCYAPI_KEYS", "").split(",")
    if key.strip()
]
DRY_RUN = os.environ.get("DRY_RUN", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

TEHRAN = pytz.timezone("Asia/Tehran")
NOBITEX_URL = (
    "https://apiv2.nobitex.ir/market/stats"
    "?srcCurrency=usdt&dstCurrency=rls"
)
WALLEX_URL = "https://api.wallex.ir/v1/markets"
CURRENCYAPI_URL = "https://api.currencyapi.com/v3/latest"

WORK_START_HOUR = 9
WORK_END_HOUR = 22
POST_MINUTE = 45
GRACE_MINUTES = 2
HTTP_TIMEOUT = 15
TELEGRAM_ATTEMPTS = 3
TELEGRAM_BASE_DELAY = 2
TELEGRAM_MAX_LEN = 4096
SLOT_RETENTION_DAYS = 7
FX_CACHE_TTL_SECONDS = 6 * 60 * 60

HAWALA_DEFAULT_PAYOUT_FACTOR = Decimal("0.98")
HAWALA_TRY_PAYOUT_FACTOR = Decimal("0.94")
USDT_RLS_LOW = Decimal("300000")
USDT_RLS_HIGH = Decimal("3000000")
USDT_USD_LOW = Decimal("0.90")
USDT_USD_HIGH = Decimal("1.10")

CCXT_OPTIONS = {
    "enableRateLimit": True,
    "timeout": 10000,
}

HAWALA_CURRENCIES = [
    ("USD", "🇺🇸", "دلار آمریکا"),
    ("EUR", "🇪🇺", "یورو"),
    ("GBP", "🇬🇧", "پوند انگلیس"),
    ("CAD", "🇨🇦", "دلار کانادا"),
    ("AUD", "🇦🇺", "دلار استرالیا"),
    ("SEK", "🇸🇪", "کرون سوئد"),
    ("TRY", "🇹🇷", "لیر ترکیه"),
]
CONVERSION_CODES = [
    code
    for code, _flag, _name in HAWALA_CURRENCIES
    if code != "USD"
]
HAWALA_CTA = os.environ.get(
    "HAWALA_CTA",
    (
        "🔹 جهت ثبت سفارش حواله با نرخ لحظه‌ای و یا استعلام قیمت سایر ارزها، "
        "از راه‌های ارتباطی زیر استفاده بفرمایید 👇🏻\n"
        "📱 Telegram: https://t.me/TL905411603664\n"
        "📱 WhatsApp: https://wa.me/905392905686"
    ),
)
FA_DIGITS = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹،")
PERSIAN_WEEKDAYS = [
    "شنبه",
    "یک‌شنبه",
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنج‌شنبه",
    "جمعه",
]
PERSIAN_MONTHS = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]

logger = logging.getLogger("kiani_hawala_bot")
_shutdown = False
_fx_crosses_cache: Optional[Dict[str, Decimal]] = None
_fx_crosses_cache_fetched_at: Optional[float] = None


def _parse_chat_id(value: str) -> Union[int, str]:
    try:
        return int(value)
    except ValueError:
        return value


TELEGRAM_CHANNEL_ID = _parse_chat_id(TELEGRAM_CHANNEL_ID_RAW)
try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW) if ADMIN_CHAT_ID_RAW else None
except ValueError:
    ADMIN_CHAT_ID = None


def _build_session() -> requests.Session:
    session = requests.Session()
    retry_kwargs = {
        "total": 2,
        "connect": 2,
        "read": 2,
        "backoff_factor": 0.5,
        "status_forcelist": [429, 500, 502, 503, 504],
        "raise_on_status": False,
    }
    try:
        retry = Retry(
            allowed_methods=frozenset(["GET"]),
            **retry_kwargs,
        )
    except TypeError:
        retry = Retry(
            method_whitelist=frozenset(["GET"]),
            **retry_kwargs,
        )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


HTTP = _build_session()
telegram_bot = (
    telebot.TeleBot(TELEGRAM_BOT_TOKEN)
    if TELEGRAM_BOT_TOKEN
    else None
)


def _proxy_mapping() -> Optional[Dict[str, str]]:
    if not PROXY_URL:
        return None
    return {
        "http": PROXY_URL,
        "https": PROXY_URL,
    }


def setup_logging() -> None:
    os.makedirs(BASE_DIR, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH,
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s:%(message)s"
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


def validate_configuration() -> None:
    missing = []
    if not TELEGRAM_BOT_TOKEN and not DRY_RUN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHANNEL_ID and not DRY_RUN:
        missing.append("TELEGRAM_CHANNEL_ID")
    if not CURRENCYAPI_KEYS:
        missing.append("CURRENCYAPI_KEYS")
    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )


def _to_decimal(value) -> Optional[Decimal]:
    try:
        if value is None:
            return None
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            return None
        return number
    except (InvalidOperation, ValueError, TypeError):
        return None


def _format_fa_number(value: int) -> str:
    return "{:,}".format(value).translate(FA_DIGITS)


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, timeout=10)


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posted_slots (
                slot_key TEXT PRIMARY KEY,
                posted_at TEXT NOT NULL
            )
            """
        )


def db_slot_posted(slot_key: str) -> bool:
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM posted_slots WHERE slot_key = ?",
                (slot_key,),
            ).fetchone()
        return row is not None
    except Exception:
        logger.exception(
            "Could not verify slot %s; treating it as posted.",
            slot_key,
        )
        return True


def db_mark_slot_posted(slot_key: str) -> bool:
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO posted_slots (
                    slot_key,
                    posted_at
                ) VALUES (?, ?)
                """,
                (
                    slot_key,
                    datetime.now(TEHRAN).isoformat(),
                ),
            )
        return True
    except Exception:
        logger.exception("Could not record posted slot %s", slot_key)
        return False


def prune_old_slots() -> None:
    try:
        cutoff = (
            datetime.now(TEHRAN)
            - timedelta(days=SLOT_RETENTION_DAYS)
        ).isoformat()
        with _connect() as conn:
            conn.execute(
                "DELETE FROM posted_slots WHERE posted_at < ?",
                (cutoff,),
            )
    except Exception:
        logger.exception("Could not prune old slots.")


def fetch_nobitex_usdt_rls() -> Optional[Decimal]:
    try:
        response = HTTP.get(
            NOBITEX_URL,
            proxies=_proxy_mapping(),
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            logger.warning("Nobitex returned malformed JSON.")
            return None
        if payload.get("status") != "ok":
            logger.warning(
                "Nobitex returned non-ok status: %s",
                payload.get("status"),
            )
            return None
        market = payload.get("stats", {}).get("usdt-rls")
        if not isinstance(market, dict):
            logger.warning("Nobitex stats.usdt-rls is missing.")
            return None
        if market.get("isClosed") is True:
            logger.warning("Nobitex USDT/RLS market is closed.")
            return None
        value = _to_decimal(market.get("latest"))
        if value is None:
            logger.warning(
                "Nobitex returned invalid latest value: %r",
                market.get("latest"),
            )
            return None
        if not (USDT_RLS_LOW <= value <= USDT_RLS_HIGH):
            logger.warning(
                "Nobitex USDT/RLS is out of bounds: %s",
                value,
            )
            return None
        return value
    except requests.RequestException as exc:
        logger.warning(
            "Nobitex USDT/RLS request failed: %s",
            exc,
        )
        return None
    except (ValueError, TypeError) as exc:
        logger.warning(
            "Nobitex response parsing failed: %s",
            exc,
        )
        return None


def fetch_wallex_usdt_rls() -> Optional[Decimal]:
    headers = {"User-Agent": "KianiHawalaBot/1.0"}
    if WALLEX_API_KEY:
        headers["X-API-Key"] = WALLEX_API_KEY
    try:
        response = HTTP.get(
            WALLEX_URL,
            headers=headers,
            proxies=_proxy_mapping(),
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        market = (
            response.json()
            .get("result", {})
            .get("symbols", {})
            .get("USDTTMN")
        )
        if not isinstance(market, dict):
            logger.warning("Wallex USDTTMN market is missing.")
            return None
        stats = market.get("stats")
        if not isinstance(stats, dict):
            logger.warning("Wallex USDTTMN stats are missing.")
            return None
        toman_value = _to_decimal(stats.get("lastPrice"))
        if toman_value is None:
            logger.warning(
                "Wallex returned invalid USDTTMN lastPrice."
            )
            return None
        rial_value = toman_value * Decimal("10")
        if not (USDT_RLS_LOW <= rial_value <= USDT_RLS_HIGH):
            logger.warning(
                "Wallex USDT/RLS is out of bounds: %s",
                rial_value,
            )
            return None
        return rial_value
    except requests.RequestException as exc:
        logger.warning(
            "Wallex USDT/RLS request failed: %s",
            exc,
        )
        return None
    except (ValueError, TypeError) as exc:
        logger.warning(
            "Wallex response parsing failed: %s",
            exc,
        )
        return None


def get_usdt_rls() -> Optional[Decimal]:
    value = fetch_nobitex_usdt_rls()
    if value is not None:
        return value
    logger.warning(
        "Nobitex unavailable; trying Wallex fallback."
    )
    value = fetch_wallex_usdt_rls()
    if value is None:
        logger.error(
            "No valid USDT/RLS source; skipping post."
        )
    return value


def _ccxt_last(exchange_factory, symbol: str, label: str) -> Optional[Decimal]:
    try:
        ticker = exchange_factory().fetch_ticker(symbol)
        if not isinstance(ticker, dict):
            logger.warning("%s returned malformed ticker.", label)
            return None
        value = _to_decimal(ticker.get("last"))
        if value is None:
            logger.warning("%s returned invalid last price.", label)
        return value
    except Exception as exc:
        logger.warning("%s fetch failed: %s", label, exc)
        return None


def get_usdt_usd() -> Optional[Decimal]:
    primary = _ccxt_last(
        lambda: ccxt.gateio(CCXT_OPTIONS),
        "USDT/USD",
        "Gate.io USDT/USD",
    )
    if (
        primary is not None
        and USDT_USD_LOW <= primary <= USDT_USD_HIGH
    ):
        return primary

    logger.warning(
        "Primary USDT/USD unavailable or invalid; "
        "trying Kraken."
    )
    secondary = _ccxt_last(
        lambda: ccxt.kraken(CCXT_OPTIONS),
        "USDT/USD",
        "Kraken USDT/USD",
    )
    if (
        secondary is None
        or not (USDT_USD_LOW <= secondary <= USDT_USD_HIGH)
    ):
        logger.error(
            "No valid USDT/USD source; skipping post."
        )
        return None
    return secondary


def fetch_currencyapi_crosses() -> Optional[Dict[str, Decimal]]:
    currencies = ",".join(CONVERSION_CODES)
    for key in CURRENCYAPI_KEYS:
        try:
            response = HTTP.get(
                CURRENCYAPI_URL,
                headers={
                    "apikey": key,
                    "User-Agent": "KianiHawalaBot/1.0",
                },
                params={
                    "base_currency": "USD",
                    "currencies": currencies,
                },
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            data = (
                payload.get("data")
                if isinstance(payload, dict)
                else None
            )
            if not isinstance(data, dict):
                logger.warning(
                    "CurrencyAPI returned no data; trying next key."
                )
                continue

            crosses: Dict[str, Decimal] = {}
            complete = True
            for code in CONVERSION_CODES:
                entry = data.get(code)
                value = _to_decimal(
                    entry.get("value")
                    if isinstance(entry, dict)
                    else None
                )
                if value is None:
                    logger.warning(
                        "CurrencyAPI missing/invalid %s; "
                        "discarding key result.",
                        code,
                    )
                    complete = False
                    break
                crosses[code] = value

            if complete:
                return crosses
        except requests.RequestException as exc:
            logger.warning(
                "CurrencyAPI key failed; trying next: %s",
                exc,
            )
        except (ValueError, TypeError) as exc:
            logger.warning(
                "CurrencyAPI parsing failed; trying next key: %s",
                exc,
            )
    return None


def get_currency_crosses() -> Optional[Dict[str, Decimal]]:
    global _fx_crosses_cache
    global _fx_crosses_cache_fetched_at

    now = time.monotonic()
    if (
        _fx_crosses_cache is not None
        and _fx_crosses_cache_fetched_at is not None
    ):
        cache_age = now - _fx_crosses_cache_fetched_at
        if cache_age < FX_CACHE_TTL_SECONDS:
            return _fx_crosses_cache

    fresh = fetch_currencyapi_crosses()
    if fresh is not None:
        _fx_crosses_cache = fresh
        _fx_crosses_cache_fetched_at = time.monotonic()
        return fresh

    if (
        _fx_crosses_cache is not None
        and _fx_crosses_cache_fetched_at is not None
    ):
        cache_age = time.monotonic() - _fx_crosses_cache_fetched_at
        logger.warning(
            "CurrencyAPI unavailable; using stale FX cache "
            "(age %.2f hours).",
            cache_age / 3600,
        )
        return _fx_crosses_cache

    logger.error(
        "CurrencyAPI unavailable and no cache exists; "
        "skipping post."
    )
    return None


def calculate_hawala_rates() -> Optional[Dict[str, int]]:
    usdt_rls = get_usdt_rls()
    if usdt_rls is None:
        return None

    usdt_usd = get_usdt_usd()
    if usdt_usd is None:
        return None

    crosses = get_currency_crosses()
    if crosses is None:
        return None

    usd_rls = usdt_rls / usdt_usd
    rates: Dict[str, int] = {}

    for code, _flag, _name in HAWALA_CURRENCIES:
        if code == "USD":
            market_rls = usd_rls
        else:
            cross = crosses.get(code)
            if cross is None or cross <= 0:
                logger.warning(
                    "Missing or invalid USD/%s cross; "
                    "skipping post.",
                    code,
                )
                return None
            market_rls = usd_rls / cross

        market_toman = market_rls / Decimal("10")
        payout_factor = (
            HAWALA_TRY_PAYOUT_FACTOR
            if code == "TRY"
            else HAWALA_DEFAULT_PAYOUT_FACTOR
        )
        customer_rate = market_toman * payout_factor
        rounded_rate = int(
            customer_rate.quantize(
                Decimal("1E2"),
                rounding=ROUND_HALF_EVEN,
            )
        )
        if rounded_rate <= 0:
            logger.warning(
                "Calculated %s rate is invalid: %s",
                code,
                rounded_rate,
            )
            return None
        rates[code] = rounded_rate

    return rates


def get_persian_date() -> str:
    now = jdatetime.datetime.now(TEHRAN)
    return "📆 {}، {} {} {} {}".format(
        PERSIAN_WEEKDAYS[now.weekday()],
        now.day,
        PERSIAN_MONTHS[now.month - 1],
        now.year,
        now.strftime("%H:%M:%S"),
    )


def build_hawala_message(rates: Dict[str, int]) -> str:
    lines = [
        get_persian_date(),
        "",
        "💱 نرخ حواله به ایران",
        "",
    ]
    for code, flag, name in HAWALA_CURRENCIES:
        lines.append(
            "{} حواله {} به ایران: {} تومان".format(
                flag,
                name,
                _format_fa_number(rates[code]),
            )
        )
    lines.extend(["", HAWALA_CTA])
    return "\n".join(lines)


def _sleep_interruptible(seconds: float) -> None:
    end = time.monotonic() + seconds
    while not _shutdown and time.monotonic() < end:
        time.sleep(min(1.0, end - time.monotonic()))


def post_message(message: str) -> bool:
    if len(message) > TELEGRAM_MAX_LEN:
        logger.error(
            "Message too long (%d > %d); skipping.",
            len(message),
            TELEGRAM_MAX_LEN,
        )
        return False

    if DRY_RUN:
        logger.info("DRY_RUN message:\n%s", message)
        return True

    if telegram_bot is None:
        logger.error("Telegram client is unavailable.")
        return False

    for attempt in range(1, TELEGRAM_ATTEMPTS + 1):
        telebot.apihelper.proxy = _proxy_mapping() or None
        try:
            telegram_bot.send_message(
                TELEGRAM_CHANNEL_ID,
                message,
            )
            return True
        except Exception as exc:
            logger.warning(
                "Telegram send attempt %d/%d failed: %s",
                attempt,
                TELEGRAM_ATTEMPTS,
                exc,
            )
            if attempt < TELEGRAM_ATTEMPTS:
                _sleep_interruptible(
                    TELEGRAM_BASE_DELAY * (2 ** (attempt - 1))
                )
        finally:
            telebot.apihelper.proxy = None

    logger.error(
        "Telegram send failed after %d attempts.",
        TELEGRAM_ATTEMPTS,
    )
    return False


def fire_alert(message: str) -> None:
    logger.critical("ALERT: %s", message)
    if (
        ADMIN_CHAT_ID is None
        or telegram_bot is None
        or DRY_RUN
    ):
        return
    try:
        telegram_bot.send_message(
            ADMIN_CHAT_ID,
            "⚠️ Hawala bot alert: " + message,
        )
    except Exception:
        logger.exception("Failed to deliver admin alert.")


def acquire_lock():
    os.makedirs(BASE_DIR, exist_ok=True)
    lock_handle = open(LOCK_PATH, "w", encoding="utf-8")
    try:
        fcntl.flock(
            lock_handle.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except OSError as exc:
        lock_handle.close()
        raise RuntimeError(
            "Another hawala bot instance is running."
        ) from exc
    lock_handle.write(str(os.getpid()))
    lock_handle.flush()
    return lock_handle


def _handle_signal(signum, _frame) -> None:
    global _shutdown
    logger.info("Received signal %s; shutting down.", signum)
    _shutdown = True


def process_current_slot() -> None:
    now = datetime.now(TEHRAN)
    if not (WORK_START_HOUR <= now.hour < WORK_END_HOUR):
        return

    scheduled_at = now.replace(
        minute=POST_MINUTE,
        second=0,
        microsecond=0,
    )
    deadline = scheduled_at + timedelta(minutes=GRACE_MINUTES)
    if not (scheduled_at <= now < deadline):
        return

    slot_key = "{} {:02d}:{:02d}:hawala".format(
        now.date().isoformat(),
        now.hour,
        POST_MINUTE,
    )
    if db_slot_posted(slot_key):
        return

    rates = calculate_hawala_rates()
    if rates is None:
        logger.warning(
            "Hawala post deferred for slot %s: "
            "required data unavailable.",
            slot_key,
        )
        return

    if not post_message(build_hawala_message(rates)):
        logger.error(
            "Hawala send failed for slot %s; "
            "will retry inside grace window.",
            slot_key,
        )
        return

    if not db_mark_slot_posted(slot_key):
        fire_alert(
            "Message sent but slot persistence failed: "
            + slot_key
        )

    logger.info("Hawala message posted for slot %s", slot_key)


def main() -> None:
    setup_logging()
    try:
        validate_configuration()
        lock_handle = acquire_lock()
    except Exception as exc:
        logger.critical("Startup failed: %s", exc)
        raise SystemExit(1) from exc

    try:
        init_db()
        prune_old_slots()
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
        logger.info(
            "Starting standalone hawala bot "
            "(strict mode, :%02d Tehran).",
            POST_MINUTE,
        )

        while not _shutdown:
            try:
                process_current_slot()
            except Exception:
                logger.exception("Unhandled scheduler exception.")
            _sleep_interruptible(30)
    finally:
        telebot.apihelper.proxy = None
        try:
            HTTP.close()
        except Exception:
            logger.exception("Failed to close HTTP session.")
        try:
            lock_handle.close()
        except Exception:
            logger.exception("Failed to close lock handle.")
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()

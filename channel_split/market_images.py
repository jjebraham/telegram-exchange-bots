"""Render approved AlanChande market bulletins as PNG images, then upload with Telegram sendPhoto.

The renderer is deliberately offline: it only parses the *already validated* message
from publish_channels.py. It cannot fetch rates or weaken the publisher's safety checks.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape, unescape
from pathlib import Path
import json
import os
import re
import shutil
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SUPPORTED_MARKETS = frozenset({"usdt", "iran-fx", "iran-gold", "turkey-gold", "fx-pulse"})
TITLES = {
    "usdt": "قیمت تتر در صرافی‌های ایران",
    "iran-fx": "نرخ ارز آزاد ایران",
    "iran-gold": "طلا و سکه ایران",
    "turkey-gold": "قیمت طلای ترکیه",
    "fx-pulse": "نبض بازار ارز ترکیه",
}
EXCHANGES = {
    "Wallex":"والکس", "Nobitex":"نوبیتکس", "Ramzinex":"رمزینکس",
    "Bitpin":"بیت‌پین", "Tabdeal":"تبدیل", "Exir":"اکسیر",
    "AbanTether":"آبان تتر", "Raastin":"راستین",
}
CURRENCY_NAMES = {
    "USD":"دلار آمریکا", "EUR":"یورو", "GBP":"پوند انگلیس",
    "CHF":"فرانک سوئیس", "CAD":"دلار کانادا", "AUD":"دلار استرالیا",
    "SEK":"کرون سوئد", "NOK":"کرون نروژ", "RUB":"روبل روسیه",
    "THB":"بات تایلند", "SGD":"دلار سنگاپور", "HKD":"دلار هنگ‌کنگ",
    "AZN":"منات آذربایجان", "DKK":"کرون دانمارک", "AED":"درهم امارات",
    "TRY":"لیر ترکیه", "CNY":"یوان چین", "SAR":"ریال عربستان",
    "INR":"روپیه هند", "MYR":"رینگیت مالزی", "AFN":"افغانی",
    "KWD":"دینار کویت", "BHD":"دینار بحرین", "OMR":"ریال عمان",
    "QAR":"ریال قطر",
}
GOLD_TR = {
    "GRAM":("گرم طلا","Gram Altın"),
    "CEYREK":("ربع سکه","Çeyrek Altın"),
    "YARIM":("نیم سکه","Yarım Altın"),
    "TAM":("تمام سکه","Tam Altın"),
}
PCT = r"[+\-−]?\d+(?:\.\d+)?%|—"
RATE = r"[\d,.]+|—"


def _pre(text: str) -> list[str]:
    match = re.search(r"<pre>(.*?)</pre>", text, re.S)
    if not match:
        raise ValueError("Missing approved preformatted market table")
    lines = unescape(match.group(1)).splitlines()
    return [line.strip("\u200e ").strip() for line in lines[1:] if line.strip()]


def _number(text: str, klass: str = "price") -> str:
    return f'<span class="{klass}" dir="ltr">{escape(text)}</span>'


def _percent(text: str) -> str:
    klass = "up" if text.startswith("+") else "down" if text.startswith(("-", "−")) else "muted"
    return _number(text or "—", klass)


def _table(columns: list[str], rows: list[list[str]], *, split: bool = False) -> str:
    def table(chunk: list[list[str]]) -> str:
        heads = "".join(f"<th>{escape(col)}</th>" for col in columns)
        cells = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in chunk)
        return f"<table><thead><tr>{heads}</tr></thead><tbody>{cells}</tbody></table>"
    if split:
        middle = (len(rows) + 1) // 2
        return f'<section class="split">{table(rows[:middle])}{table(rows[middle:])}</section>'
    return table(rows)


def _usdt(text: str) -> str:
    pattern = re.compile(rf"^(.+?)\s+({RATE})\s+({RATE})\s+({PCT})\s+({PCT})$")
    rows = []
    for line in _pre(text):
        match = pattern.fullmatch(line)
        if not match:
            raise ValueError(f"Malformed USDT row: {line!r}")
        name, buy, sell, day, month = match.groups()
        if name not in EXCHANGES:
            raise ValueError(f"Unrecognized exchange: {name}")
        rows.append([f"<strong>{escape(EXCHANGES[name])}</strong>", _number(buy, "red"),
                     _number(sell), _percent(day), _percent(month)])
    if not 5 <= len(rows) <= 12:
        raise ValueError("USDT source count outside expected range")
    board = _table(["صرافی","قیمت خرید","قیمت فروش","۲۴ ساعت","۱ ماه"], rows)
    summaries = []
    for label in ("میانگین قیمت خرید","میانگین قیمت فروش","کمترین قیمت خرید","بیشترین قیمت فروش"):
        match = re.search(rf"{label}:\s*(?:<b>([^<]+)</b>\s*)?<code>([^<]+)</code>", text)
        if not match:
            raise ValueError(f"Missing approved USDT summary: {label}")
        name, price = match.groups()
        caption = escape(EXCHANGES.get(name, name)) if name else ""
        summaries.append(f'<div class="summary"><small>{label}</small><strong>{_number(price)}</strong><small>{caption}</small></div>')
    return board + '<section class="summaries">' + "".join(summaries) + "</section>"


def _iran_fx(text: str) -> str:
    pattern = re.compile(rf"^(\S+)\s+([A-Z]{{3}})\s+({RATE})\s+({PCT})\s+({PCT})$")
    rows = []
    for line in _pre(text):
        match = pattern.fullmatch(line)
        if not match:
            raise ValueError(f"Malformed Iran FX row: {line!r}")
        flag, code, price, day, month = match.groups()
        if code not in CURRENCY_NAMES:
            raise ValueError(f"Unknown currency: {code}")
        name = escape(CURRENCY_NAMES[code])
        rows.append([f'<span class="name">{escape(flag)} {name}<small>{code}</small></span>',
                     _number(price), _percent(day), _percent(month)])
    if not 23 <= len(rows) <= 25:
        raise ValueError(f"Unexpected Iranian FX row count: {len(rows)}")
    return _table(["ارز","قیمت","۲۴ ساعت","۱ ماه"], rows, split=True)


def _iran_gold(text: str) -> str:
    pattern = re.compile(rf"<b>([^<]+)</b>\s*<code>({RATE})</code>\s*({PCT})")
    rows = []
    for line in text.splitlines():
        match = pattern.search(line)
        if match:
            name, price, day = match.groups()
            coin = "▰" if "طلا" in name or "مثقال" in name else "●"
            rows.append([f'<span class="name"><em>{coin}</em>{escape(name)}</span>',
                         _number(price), _percent(day), _percent("—")])
    if not 5 <= len(rows) <= 7:
        raise ValueError("Missing Iranian gold rows")
    return _table(["نوع","قیمت بازار","۲۴ ساعت","۱ ماه"], rows)


def _turkey_gold(text: str) -> str:
    rows = []
    for line in _pre(text):
        columns = line.removeprefix("🌕").split()
        if len(columns) != 4 or columns[0] not in GOLD_TR:
            raise ValueError(f"Malformed Turkish gold row: {line!r}")
        kind, sell, buy, day = columns
        name, latin = GOLD_TR[kind]
        rows.append([f'<span class="name"><em>●</em>{name}<small>{latin}</small></span>',
                     _number(sell, "red"), _number(buy, "up"), _percent(day), _percent("—")])
    if len(rows) != 4:
        raise ValueError("Missing Turkish gold rows")
    return _table(["نوع طلا","فروش","خرید","۲۴ ساعت","۱ ماه"], rows)


def _pulse(text: str) -> str:
    rows = []
    for line in _pre(text):
        match = re.search(rf"(USD/TL|EUR/TL)\s+(\d+\.\d{{4}})\s+({PCT})", line)
        if not match:
            raise ValueError(f"Malformed TRY FX pulse row: {line!r}")
        pair, value, day = match.groups()
        flags = "🇺🇸 🇹🇷" if pair == "USD/TL" else "🇪🇺 🇹🇷"
        label = "دلار آمریکا به لیر" if pair == "USD/TL" else "یورو به لیر"
        rows.append(f'<section class="pulse"><div><div class="flags">{flags}</div><h2 dir="ltr">{pair}</h2><small>{label}</small></div>'
                    f'<div class="mainprice">{escape(value)}<small>لیر ترکیه</small></div>'
                    f'<div class="changes">۲۴ ساعت {_percent(day)}<hr>۱ ماه {_percent("—")}</div></section>')
    if len(rows) != 2 or "USD/TL" not in text or "EUR/TL" not in text:
        raise ValueError("Missing USD/TL or EUR/TL market")
    return "".join(rows)


def _jalali(now: datetime) -> str:
    gy, gm, gd = now.year, now.month, now.day
    months = [0,31,59,90,120,151,181,212,243,273,304,334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365*gy + (gy2+3)//4 - (gy2+99)//100 + (gy2+399)//400 + gd + months[gm-1]
    jy = -1595 + 33*(days//12053)
    days %= 12053
    jy += 4*(days//1461)
    days %= 1461
    if days > 365:
        jy += (days-1)//365
        days = (days-1)%365
    if days < 186:
        jm, jd = 1+days//31, 1+days%31
    else:
        jm, jd = 7+(days-186)//30, 1+(days-186)%30
    weekdays = ["دوشنبه","سه‌شنبه","چهارشنبه","پنجشنبه","جمعه","شنبه","یکشنبه"]
    month_names = ["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"]
    return f"{weekdays[now.weekday()]} {jd} {month_names[jm-1]} {jy}"


PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

CSS = """
*{box-sizing:border-box}
html,body{margin:0;padding:0}body{font-family:"Vazirmatn","Noto Sans Arabic","Noto Naskh Arabic","DejaVu Sans",Tahoma,sans-serif;background:#fff;color:#141638}
.canvas{width:1200px;height:var(--height);direction:rtl;display:flex;flex-direction:column;overflow:hidden;background:#fff}
.header{height:116px;background:#493eb6;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 42px;font-size:36px;font-weight:800;flex-shrink:0}
.header .time{color:#ffe47d}.header small{font-size:22px;color:#fff;font-weight:500}
.stripe{height:10px;background:linear-gradient(90deg,#f07b77 0 53%,#75d9dc 53%);flex-shrink:0}
.title{min-height:150px;border-bottom:3px solid #493eb6;padding:25px 42px;display:flex;align-items:center;justify-content:space-between;gap:20px;flex-shrink:0}
.title h1{margin:0;color:#493eb6;font-size:52px;border-right:11px solid #efa922;padding-right:22px}.title .subtitle{color:#656981;font-size:22px}
.main{flex:1;min-height:0;padding:26px 40px 18px;display:flex;flex-direction:column;gap:18px}
table{border-collapse:separate;border-spacing:0;width:100%;table-layout:fixed;direction:rtl;border:1px solid #e4e6f3;border-radius:18px;overflow:hidden;font-size:26px}
th{background:#eff0f9;padding:16px 8px;color:#50536f;font-size:23px}
td{background:#fff;padding:14px 9px;border-bottom:1px solid #e8e9f4;text-align:center;font-weight:800;height:78px}
tr:nth-child(even) td{background:#fafaff}tbody tr:last-child td{border:0}
td:first-child,th:first-child{width:28%;text-align:right;padding-right:18px}
.name{display:flex;align-items:center;gap:10px;font-size:22px;text-align:right}.name small{display:block;font:600 16px Arial,sans-serif;color:#888;direction:ltr}
.name em{color:#d9a326;font-style:normal;font-size:33px}.price{color:#151538}.red{color:#ce1536}.up{color:#087f3d}.down{color:#ce1536}.muted{color:#888aa3}
.summary{background:#f6f8ff;border:1px solid #cfd7f2;border-radius:16px;padding:16px 22px;min-height:100px;display:flex;flex-direction:column;gap:5px}
.summary strong{font-size:34px}.summary small{font-size:17px;color:#555c79}
.summaries{display:grid;grid-template-columns:1fr 1fr;gap:13px}
.split{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.split table{font-size:17px}.split th{font-size:17px;padding:9px 3px}
.split td{height:67px;padding:8px 3px;font-size:17px}.split td:first-child,.split th:first-child{width:38%;padding-right:7px}
.split .name{font-size:16px}.split .name small{font-size:12px}
.pulse{min-height:285px;border:2px solid #dedff3;border-radius:24px;display:grid;grid-template-columns:29% 42% 29%;align-items:center;padding:34px 22px}
.pulse h2{font-size:39px;margin:9px 0}.pulse small{font-size:22px;color:#626784}.pulse .flags{font-size:48px}
.mainprice{font-size:75px;font-weight:900;color:#ce1233;direction:ltr;white-space:nowrap}.mainprice small{display:block;text-align:center;direction:rtl}
.changes{padding:18px;border-radius:18px;background:#f3f5fd;font-size:20px;text-align:center}
.footer{height:93px;background:#493eb6;color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 45px;flex-shrink:0;font-size:19px}
.footer b{font:800 29px Arial,sans-serif;color:#ffe47d}
.iran-fx .main{padding:22px 18px}.usdt td{height:78px}.turkey-gold td{height:140px}.iran-gold td{height:100px}
"""

def html_for_post(kind: str, text: str, *, now: datetime | None = None) -> str:
    if kind not in SUPPORTED_MARKETS:
        raise ValueError(f"Unsupported image template: {kind}")
    tz = "Asia/Tehran" if kind in {"usdt","iran-fx","iran-gold"} else "Europe/Istanbul"
    now = now.astimezone(ZoneInfo(tz)) if now else datetime.now(ZoneInfo(tz))
    date = _jalali(now).translate(PERSIAN_DIGITS)
    time = now.strftime("%H:%M").translate(PERSIAN_DIGITS)
    city = "تهران" if tz == "Asia/Tehran" else "استانبول"
    content = {"usdt":_usdt,"iran-fx":_iran_fx,"iran-gold":_iran_gold,
               "turkey-gold":_turkey_gold,"fx-pulse":_pulse}[kind](text)
    heights = {"usdt":1550,"iran-fx":1580,"iran-gold":1280,"turkey-gold":1280,"fx-pulse":1180}
    subtitle = {"usdt":"ارقام به تومان","iran-fx":"ارقام به تومان",
                "iran-gold":"قیمت بازار · ارقام به تومان",
                "turkey-gold":"بازار Kapalıçarşı · لیر ترکیه",
                "fx-pulse":"نرخ میانی دلار و یورو · Kapalıçarşı"}[kind]
    return (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>'
            f':root{{--height:{heights[kind]}px}}{CSS}</style></head><body><div class="canvas {kind}">'
            f'<header class="header"><span>{escape(date)}</span>'
            f'<span class="time">{escape(time)} <small>{city}</small></span></header>'
            f'<div class="stripe"></div><section class="title"><h1>{escape(TITLES[kind])}</h1>'
            f'<div class="subtitle">{escape(subtitle)}</div></section><main class="main">'
            f'{content}</main><div class="stripe"></div><footer class="footer">'
            f'<span>قیمت‌ها صرفاً جهت اطلاع‌رسانی است.</span><b dir="ltr">@alanchande_com</b>'
            f'</footer></div></body></html>')


def _screenshot_html(html: str, target: Path) -> None:
    """Browser-only worker; called under a dedicated image-rendering venv if necessary."""
    from playwright.sync_api import sync_playwright
    executable = (
        os.environ.get("ALANCHANDE_CHROMIUM_PATH")
        or shutil.which("chromium")
        or shutil.which("google-chrome")
        or None
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=executable, args=["--no-sandbox"]
        )
        try:
            page = browser.new_page(
                viewport={"width": 1200, "height": 1700}, device_scale_factor=1
            )
            page.set_content(html, wait_until="load")
            page.evaluate("document.fonts.ready")
            page.locator(".canvas").screenshot(path=str(target))
        finally:
            browser.close()


def render_png(kind: str, approved_text: str, output: Path | str) -> Path:
    """Render a verified rate card. Keep publisher's system Python unchanged."""
    import importlib.util
    import subprocess
    import sys

    html = html_for_post(kind, approved_text)
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if importlib.util.find_spec("playwright") and os.environ.get("ALANCHANDE_RENDER_FORCE_WORKER") != "1":
        _screenshot_html(html, target)
    else:
        worker_python = Path(
            os.environ.get("ALANCHANDE_RENDER_PYTHON", "")
            or (Path.home() / ".venvs/alanchande-images/bin/python")
        )
        if not worker_python.is_file():
            raise RuntimeError("Dedicated AlanChande image renderer venv is missing")
        result = subprocess.run(
            [str(worker_python), str(Path(__file__).resolve()), "--render-worker", str(target)],
            input=html,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=75,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Dedicated image renderer failed (no Telegram photo sent): "
                + result.stderr[-600:]
            )
    if not target.is_file() or not 5_000 <= target.stat().st_size <= 9_500_000:
        raise RuntimeError("PNG size is outside Telegram sendPhoto range")
    return target


def telegram_send_photo(token: str, chat_id: str, photo: Path | str, caption: str, *, timeout: int = 35) -> dict:
    """sendPhoto without printing the bot token."""
    boundary = "AlanChande" + uuid.uuid4().hex
    def field(name: str, val: str) -> bytes:
        return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n').encode()
    png = Path(photo).read_bytes()
    body = b"".join([field("chat_id",chat_id), field("caption",caption[:1024]),
                     field("disable_notification","true"),
                     (f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="market.png"\r\nContent-Type: image/png\r\n\r\n').encode(),
                     png,b"\r\n",(f"--{boundary}--\r\n").encode()])
    req = Request(f"https://api.telegram.org/bot{token}/sendPhoto",
                  data=body, headers={"Content-Type":f"multipart/form-data; boundary={boundary}"})
    try:
        with urlopen(req, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Telegram sendPhoto HTTP {error.code}") from None
    except (URLError,TimeoutError) as error:
        raise RuntimeError(f"Telegram sendPhoto connection failure: {type(error).__name__}") from None
    if not result.get("ok") or not isinstance(result.get("result"),dict) or "message_id" not in result["result"]:
        raise RuntimeError("Telegram sendPhoto did not return a message ID")
    return result

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3 or sys.argv[1] != "--render-worker":
        raise SystemExit("Usage: market_images.py --render-worker OUTPUT.png")
    output = Path(sys.argv[2]).resolve()
    if not output.parent.is_dir():
        raise SystemExit("Output directory does not exist")
    _screenshot_html(sys.stdin.read(), output)

"""Render approved AlanChande market bulletins as PNG images, then upload with Telegram sendPhoto.

The renderer is deliberately offline: it only parses the *already validated* message
from publish_channels.py. It cannot fetch rates or weaken the publisher's safety checks.
"""
from __future__ import annotations

from datetime import datetime
from base64 import b64encode
from functools import lru_cache
from decimal import Decimal
from html import escape, unescape
from pathlib import Path
import json
import os
import re
import shutil
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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


def _fa_num(raw: str, *, percent: bool = False) -> str:
    """Display the approved values in Persian digits; do not recalculate prices."""
    value = raw.translate(PERSIAN_DIGITS)
    if percent:
        value = value.replace(".", "٫").replace("%", "٪")
    return escape(value)


@lru_cache(maxsize=128)
def _asset_data(filename: str) -> str:
    """Embed local artwork so the renderer and its isolated worker stay offline."""
    path = Path(__file__).with_name("market_image_assets") / filename
    mime = {".ttf":"font/ttf", ".svg":"image/svg+xml", ".png":"image/png"}[path.suffix]
    return f"data:{mime};base64," + b64encode(path.read_bytes()).decode("ascii")


def _badge_icon(exchange: str) -> str:
    # Approved-reference artwork; provenance and name-only fallback are documented.
    filename = exchange.lower() + ".png"
    if not (Path(__file__).with_name("market_image_assets") / filename).is_file():
        return ""
    return f'<img class="exchange-logo" src="{_asset_data(filename)}" alt="" aria-hidden="true">'


def _usdt_percent(raw: str) -> str:
    if raw == "—":
        return '<span class="muted num">—</span>'
    value = raw.replace("−", "-")
    style = "up" if value.startswith("+") else "down" if value.startswith("-") else "muted"
    sign = value[0] if value.startswith(("+", "-")) else ""
    magnitude = value[len(sign):].removesuffix("%")
    # Separate isolated runs prevent RTL punctuation from moving the sign/percent.
    return (f'<span class="{style} num percentage" dir="ltr">'
            f'<span class="sign">{escape(sign.replace("-", "−"))}</span>'
            f'<span>{_fa_num(magnitude, percent=True)}</span><span>٪</span></span>')


def _usdt(text: str) -> str:
    """Read publisher BUY/SELL values in their existing positional convention.

    The upstream pre header says SELL/BUY, but its first value is buy_toman
    (the customer's purchase) and second is sell_toman. Never swap/recalculate.
    """
    pattern = re.compile(rf"^(.+?)\s+({RATE})\s+({RATE})\s+({PCT})\s+({PCT})$")
    rows, seen = [], set()
    for line in _pre(text):
        match = pattern.fullmatch(line)
        if not match:
            raise ValueError(f"Malformed USDT row: {line!r}")
        name, buy, sell, day, month = match.groups()
        if name not in EXCHANGES or name in seen:
            raise ValueError(f"Unknown or repeated exchange: {name}")
        seen.add(name)
        rows.append(
            f'<tr data-exchange="{name}"><td><div class="exchange-name">'
            f'{_badge_icon(name)}<strong>{escape(EXCHANGES[name])}</strong></div></td>'
            f'<td><span class="buy num" dir="ltr">{_fa_num(buy)}</span></td>'
            f'<td><span class="sell num" dir="ltr">{_fa_num(sell)}</span></td></tr>'
        )
    if not 5 <= len(rows) <= len(EXCHANGES):
        raise ValueError("USDT source count outside expected range")
    table = (
        '<section class="usdt-table"><table><thead><tr>'
        '<th>صرافی</th><th>خرید شما</th><th>فروش شما</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></section>'
    )
    summaries = []
    for label, variant in (
        ("میانگین قیمت خرید", "avg-buy"),
        ("میانگین قیمت فروش", "avg-sell"),
        ("کمترین قیمت خرید", "lowest-buy"),
        ("بیشترین قیمت فروش", "highest-sell"),
    ):
        match = re.search(
            rf"{re.escape(label)}:\s*(?:<b>([^<]+)</b>\s*)?<code>([^<]+)</code>", text)
        if match:
            exchange, price = match.groups()
            if not re.fullmatch(RATE, price):
                raise ValueError(f"Malformed USDT summary: {label}")
            if exchange:
                # Real publisher summaries use Persian names; table rows use
                # Latin display codes. Normalize names, never their values.
                key = exchange.replace("\u200c", "").replace(" ", "")
                exchange = next((code for code, name in EXCHANGES.items()
                                 if key in {code, name.replace("\u200c", "").replace(" ", "")}), None)
                if exchange not in seen:
                    raise ValueError("USDT summary names an exchange absent from the table")
        else:
            # Upstream legitimately omits sell summaries when sell data is absent.
            if variant in {"avg-buy", "lowest-buy"}:
                raise ValueError(f"Missing approved USDT summary: {label}")
            exchange, price = None, "—"
        brand = f'<span class="summary-brand">{escape(EXCHANGES[exchange])}</span>' if exchange else ""
        icon = SUMMARY_BARS if variant.startswith("avg") else SUMMARY_DOWN if variant == "lowest-buy" else SUMMARY_UP
        summaries.append(
            f'<div class="usdt-summary {variant}">'
            f'<div class="summary-label">{escape(label)}</div>'
            f'<div class="summary-price"><span class="num" dir="ltr">{_fa_num(price)}</span>'
            '<span class="unit">تومان</span></div>'
            f'<span class="summary-icon" aria-hidden="true">{icon}</span>{brand}</div>')
    return ('<div class="usdt-body">' + table
            + '<section class="usdt-summary-grid">' + "".join(summaries) + '</section></div>')



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


# Decorative SVGs contain no market values. All text and data remain HTML.
SUMMARY_BARS = '<svg viewBox="0 0 48 48"><rect x="9" y="28" width="7" height="14" rx="2"/><rect x="21" y="17" width="7" height="25" rx="2"/><rect x="33" y="6" width="7" height="36" rx="2"/></svg>'
SUMMARY_UP = '<svg viewBox="0 0 48 48"><path d="M9 37l12-15 8 6L40 12M26 12h14v14" fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
SUMMARY_DOWN = '<svg viewBox="0 0 48 48"><path d="M12 9l25 30M23 39h14V25" fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
USDT_CLOCK = '<svg viewBox="0 0 52 52" aria-hidden="true"><circle cx="26" cy="26" r="23" fill="none" stroke="#cdd9ff" stroke-width="4"/><circle cx="26" cy="26" r="19" fill="none" stroke="#fff" stroke-opacity=".5"/><path d="M26 11v15l10 9" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round"/></svg>'
USDT_CAL = '<svg viewBox="0 0 42 48" aria-hidden="true"><defs><linearGradient id="calendar" x2="0" y2="1"><stop stop-color="#fff"/><stop offset="1" stop-color="#b7cbff"/></linearGradient></defs><rect x="3" y="8" width="36" height="37" rx="5" fill="url(#calendar)"/><rect x="8" y="19" width="26" height="21" rx="1" fill="#3541b3"/><path d="M12 4v10M30 4v10" stroke="#dce7ff" stroke-width="5" stroke-linecap="round"/><path d="M12 24h3m4 0h3m4 0h3M12 30h3m4 0h3m4 0h3M12 36h3m4 0h3m4 0h3" stroke="#fff" stroke-width="3"/></svg>'
USDT_INFO = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="white"/><path d="M12 10v8M12 5v2" stroke="#4446c4" stroke-width="3"/></svg>'
USDT_TELEGRAM = '<svg class="telegram-mark" viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="tg" x2="0" y2="1"><stop stop-color="#44c8ec"/><stop offset="1" stop-color="#1589c4"/></linearGradient></defs><circle cx="32" cy="32" r="31" fill="url(#tg)"/><path d="M12 30l38-15-7 36-13-10-7 6 1-12 18-13-22 10z" fill="white"/><path d="M24 35l18-13-13 18-6 7z" fill="#b0e4f5"/></svg>'
USDT_HEADER_DECOR = '''<svg class="header-landscape" viewBox="0 0 440 130" aria-hidden="true">
<defs><pattern id="windows" width="7" height="9" patternUnits="userSpaceOnUse"><path d="M2 1v3" stroke="#6670d4" stroke-width="1.8"/></pattern></defs>
<path d="M4 130v-24h22v24h16V80h23v50h27V94h22v36h12V76h26v54h17V88h26v42h15V65h12v65h14v-29h21v29h7V92h26v38h13V80h8V65h17v65h17v-21h26v21h16v-12h24v12z" fill="#172780"/>
<path d="M43 80h22v50H43zm83-4h26v54h-26zm44 12h25v42h-25zm94 4h26v38h-26zm39-12h8V65h17v65h-25z" fill="url(#windows)"/>
<path d="M217 130V67l-10-12 15-19 15 19-10 12v63z" fill="#172780"/>
<path d="M222 36V5M208 55h28M211 50h22M214 45h16M217 40h10" stroke="#172780" stroke-width="1.3"/>
</svg>'''


def _font_css() -> str:
    return ('@font-face{font-family:AlanVazir;src:url("' + _asset_data('vazirmatn.ttf')
            + '") format("truetype");font-weight:100 900;font-display:block}')


def _validate_layout(page) -> None:
    """Fail closed before a photo is sent if any USDT dynamic field is clipped."""
    if not page.locator('.canvas.usdt').count():
        return
    errors = page.evaluate('''() => {
      const errors=[];
      const canvas=document.querySelector('.canvas').getBoundingClientRect();
      for(const e of document.querySelectorAll('.usdt th,.usdt td,.summary-label,.summary-price,.summary-brand,.header-date,.header-time,.title h1,.subtitle,.footer,.demo-label,.usdt .num')) {
        const r=e.getBoundingClientRect();
        const clipped=['hidden','clip'].includes(getComputedStyle(e).overflowY);
        if(r.left<canvas.left-.5 || r.right>canvas.right+.5 || r.bottom>canvas.bottom+.5 || e.scrollWidth>e.clientWidth+1 || (clipped && e.scrollHeight>e.clientHeight+1)) errors.push(e.className || e.tagName);
        const card=e.closest('.usdt-summary');
        if(card && e!==card) {
          const c=card.getBoundingClientRect();
          if(r.left<c.left || r.right>c.right || r.top<c.top || r.bottom>c.bottom) errors.push('summary field outside card');
        }
      }
      const body=document.querySelector('.usdt-body').getBoundingClientRect();
      const footer=document.querySelector('.footer').getBoundingClientRect();
      if(body.bottom>footer.top) errors.push('body overlaps footer');
      for(const image of document.images) if(!image.complete || !image.naturalWidth) errors.push('missing artwork');
      if(!document.fonts.check('900 40px AlanVazir')) errors.push('missing Persian font');
      return errors;
    }''')
    if errors:
        raise RuntimeError('USDT layout overflow or missing asset: ' + ', '.join(errors))


def _fit_dynamic_fields(page) -> None:
    """Allow unusually long approved values without changing their characters."""
    page.evaluate('''() => {
      for(const e of document.querySelectorAll('.usdt-table td .num,.usdt-summary .summary-price .num')) {
        const container=e.closest('td') || e.parentElement;
        const style=getComputedStyle(container);
        let available=container.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
        if(!e.closest('td')) available-=container.querySelector('.unit').getBoundingClientRect().width+parseFloat(style.gap);
        const width=e.getBoundingClientRect().width;
        if(width>available) e.style.fontSize=(parseFloat(getComputedStyle(e).fontSize)*available/width-.5)+'px';
      }
    }''')


USDT_CSS = """
.usdt.canvas{font-family:AlanVazir,sans-serif;color:#10113c;background:#f7f6fc}
.usdt>.stripe{display:none}
.usdt .header{height:120px;position:relative;isolation:isolate;overflow:hidden;padding:12px 58px 0;
 background:linear-gradient(100deg,#657efb,#4a7df0);font-size:36px;font-weight:800;line-height:1.3}
.usdt .header:before{content:"";position:absolute;z-index:-1;inset:11px 12px 0;border-radius:28px 28px 18px 18px;
 background:linear-gradient(110deg,#3436b2,#2846af 55%,#3639b3)}
.usdt .header>.header-date,.usdt .header>.header-time{position:relative;z-index:2;display:flex;align-items:center;gap:18px;white-space:nowrap}
.usdt .header .time{font-size:54px;font-weight:900;color:#ffdb60;direction:ltr;unicode-bidi:isolate}
.usdt .header-time{direction:ltr;flex-direction:row;border-right:2px solid #ffffff65;padding-right:38px}
.usdt .header-time .time{order:1}.usdt .header-time small{order:2}.usdt .header-time svg{order:0}
.usdt .header small{font-size:31px;font-weight:750;color:white}
.usdt .header svg{height:48px;width:48px;flex-shrink:0}
.usdt .header svg.header-landscape{position:absolute;z-index:0;width:440px;height:132px;left:385px;bottom:0;opacity:.28}
.usdt .title{height:150px;min-height:150px;border:0;padding:0 25px 0 36px;display:grid;grid-template-columns:140px 1fr 164px;gap:12px;align-items:center}
.usdt .hero-group{display:contents}
.usdt .title h1{font-size:60px;line-height:1.5;font-weight:900;border:0;padding:0;margin:0 -1% 0 0;width:102%;transform:scaleX(.98);letter-spacing:-2.7px;white-space:nowrap;color:#10113c;text-align:center}
.usdt .title h1 span{font-size:74px;background:linear-gradient(0deg,#3334b6,#5b59e3);background-clip:text;color:transparent}
.usdt .title .subtitle{font-size:26px;font-weight:750;color:#4d4c77;align-self:center;position:relative;padding-bottom:18px;white-space:nowrap}
.usdt .title .subtitle:after{content:"";width:78px;height:5px;position:absolute;bottom:0;left:0;background:#7d72ff;border-radius:3px}
.usdt .tether-icon{width:150px;height:140px;object-fit:contain;justify-self:end}
.usdt .main{padding:0 20px 20px;display:block;flex:1;min-height:0}
.usdt .usdt-body{display:flex;flex-direction:column;gap:18px}
.usdt-table table{border:2px solid #e2e3f5;border-radius:20px;table-layout:fixed;overflow:hidden}
.usdt-table th{height:64px;font-size:32px;font-weight:800;color:#222151;background:linear-gradient(110deg,#eff0fc,#eaeaf7);padding:8px 12px;line-height:1.4;white-space:nowrap}
.usdt-table th:first-child,.usdt-table td:first-child{width:30%;padding-right:24px;text-align:right}
.usdt-table th:not(:first-child){width:35%}
.usdt-table td{height:104px;padding:6px 16px;border-bottom:1px solid #dedff0;background:white;line-height:1.25}
.usdt-table tr:nth-child(even) td{background:#faf9fe}
.usdt-table .exchange-name{display:flex;align-items:center;gap:16px;font-size:38px;font-weight:850;white-space:nowrap}
.usdt-table .exchange-name strong{font-weight:850}
.usdt-table .exchange-logo{width:61px;height:61px;object-fit:contain;flex-shrink:0}
.usdt .num{font-family:AlanVazir,sans-serif;font-weight:900;white-space:nowrap;unicode-bidi:isolate;display:inline-block}
.usdt-table .num{font-size:70px;letter-spacing:-1.3px;line-height:1.2}
.usdt-table .percentage{font-size:41px;display:inline-flex;direction:ltr;align-items:baseline;gap:0;letter-spacing:-1px}
.usdt-table .buy{color:#db0632}.usdt-table .sell{color:#10113c}
.usdt-table .up{color:#008036}.usdt-table .down{color:#e30a33}.usdt-table .muted{color:#737197}
.usdt-summary-grid{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:144px 144px;gap:16px 24px;direction:rtl}
.usdt-summary{position:relative;border-radius:18px;border:1.5px solid #cbd9ff;background:linear-gradient(110deg,#eff3ff,#f9faff);padding:16px 26px;overflow:visible;color:#181a65}
.usdt-summary .summary-label{font-size:29px;font-weight:800;color:#454374;text-align:center;margin:0 80px 0 10px;line-height:1.4;white-space:nowrap}
.usdt-summary .summary-price{position:absolute;bottom:13px;left:32px;right:132px;display:flex;direction:rtl;align-items:baseline;justify-content:center;gap:14px;line-height:1.15;white-space:nowrap}
.usdt-summary .summary-price .num{font-size:60px;letter-spacing:-1.4px;flex-shrink:0}
.usdt-summary .unit{font-size:25px;font-weight:700;color:#454374}
.usdt-summary .summary-icon{position:absolute;left:29px;top:16px;width:60px;height:60px;border-radius:50%;display:grid;place-items:center;background:linear-gradient(120deg,#dfe7ff,#d6dfff);color:#4c4de0}
.usdt-summary .summary-icon svg{width:43px;height:43px;fill:currentColor}
.usdt-summary .summary-brand{position:absolute;right:40px;bottom:26px;font-size:27px;font-weight:850;line-height:1.4;white-space:nowrap}
.usdt-summary.avg-buy,.usdt-summary.lowest-buy{background:linear-gradient(110deg,#fff0f4,#fff8fa);border-color:#ffbdd1;color:#db0632}
.usdt-summary.avg-buy .summary-icon,.usdt-summary.lowest-buy .summary-icon{background:linear-gradient(120deg,#ffd5df,#ffbfce);color:#df0038}
.usdt-summary.highest-sell{background:linear-gradient(110deg,#effbf5,#f7fcf9);border-color:#b0e7c8;color:#007b35}
.usdt-summary.highest-sell .summary-icon{background:linear-gradient(120deg,#d6f6e4,#b9ebce);color:#00813c}
.usdt-summary.lowest-buy .summary-price,.usdt-summary.highest-sell .summary-price{right:164px;left:30px}
.usdt .footer{height:84px;background:linear-gradient(110deg,#333ac4,#3b3cb6);padding:0 44px;font-size:21px;border-top:3px solid #a6a7ef;flex-shrink:0;font-weight:450}
.usdt .footer b{font:500 27px Arial,sans-serif;color:white}
.usdt .footer .telegram-mark{width:58px;height:58px;flex-shrink:0}
.usdt .footer .handle{display:flex;direction:ltr;align-items:center;gap:16px;border-right:1px solid #ffffff60;padding-right:35px}
.usdt .footer .disclaimer{display:flex;align-items:center;gap:12px}
.usdt .footer .disclaimer svg{width:23px;height:23px;order:1;flex-shrink:0}
"""


def html_for_post(kind: str, text: str, *, now: datetime | None = None) -> str:
    if kind not in SUPPORTED_MARKETS:
        raise ValueError(f"Unsupported image template: {kind}")
    if kind != "usdt":
        from market_report_templates import render_report
        return render_report(kind, text, now)
    tz = "Asia/Tehran" if kind in {"usdt","iran-fx","iran-gold"} else "Europe/Istanbul"
    supplied_time = now is not None
    if now is not None and now.tzinfo is None:
        raise ValueError("An explicit rendering timestamp must include its timezone")
    now = now.astimezone(ZoneInfo(tz)) if now else datetime.now(ZoneInfo(tz))
    date = _jalali(now).translate(PERSIAN_DIGITS)
    time = now.strftime("%H:%M").translate(PERSIAN_DIGITS)
    if kind == "usdt" and not supplied_time:
        publisher_clock = re.search(r"🕒\s*<code>((?:[01]\d|2[0-3]):[0-5]\d)</code>\s*تهران", text)
        # The production publisher supplies its own timestamp. Missing data is
        # never presented as a newly observed market time.
        time = publisher_clock.group(1).translate(PERSIAN_DIGITS) if publisher_clock else "—"
    city = "تهران" if tz == "Asia/Tehran" else "استانبول"
    content = {"usdt":_usdt,"iran-fx":_iran_fx,"iran-gold":_iran_gold,
               "turkey-gold":_turkey_gold,"fx-pulse":_pulse}[kind](text)
    heights = {"usdt":1500 + 104 * (content.count('data-exchange=') - 7),"iran-fx":1580,"iran-gold":1280,"turkey-gold":1280,"fx-pulse":1180}
    subtitle = {"usdt":"ارقام به تومان","iran-fx":"ارقام به تومان",
                "iran-gold":"قیمت بازار · ارقام به تومان",
                "turkey-gold":"بازار Kapalıçarşı · لیر ترکیه",
                "fx-pulse":"نرخ میانی دلار و یورو · Kapalıçarşı"}[kind]
    if kind == "usdt":
        head = (
            f'<header class="header">{USDT_HEADER_DECOR}'
            f'<span class="header-date">{USDT_CAL}{escape(date)}</span>'
            f'<span class="header-time"><span class="time" dir="ltr">{escape(time)}</span>'
            f'<small>{city}</small>{USDT_CLOCK}</span></header>'
        )
        heading = (
            f'<section class="title"><div class="hero-group"><img class="tether-icon" '
            f'src="{_asset_data("tether-art.png")}" alt="">'
            '<h1><span>قیمت تتر</span> در صرافی‌های ایران</h1></div>'
            f'<div class="subtitle">{escape(subtitle)}</div></section>'
        )
        footer = (
            f'<span class="disclaimer">{USDT_INFO}قیمت‌ها صرفاً جهت اطلاع‌رسانی است.</span>'
            f'<span class="handle">{USDT_TELEGRAM}'
            '<b dir="ltr">@alanchande_com</b></span>'
        )
    else:
        head = f'<header class="header"><span>{escape(date)}</span><span class="time">{escape(time)} <small>{city}</small></span></header>'
        heading = f'<section class="title"><h1>{escape(TITLES[kind])}</h1><div class="subtitle">{escape(subtitle)}</div></section>'
        footer = '<span>قیمت‌ها صرفاً جهت اطلاع‌رسانی است.</span><b dir="ltr">@alanchande_com</b>'
    stylesheet = CSS + (_font_css() + USDT_CSS if kind == "usdt" else "")
    return (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>'
            f':root{{--height:{heights[kind]}px}}{stylesheet}</style></head><body><div class="canvas {kind}">'
            f'{head}<div class="stripe"></div>{heading}<main class="main">'
            f'{content}</main><div class="stripe"></div><footer class="footer">'
            f'{footer}</footer></div></body></html>')


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
                viewport={"width": 1200, "height": 1700},
                device_scale_factor=2,
            )
            page.route("**/*", lambda route: route.abort())
            page.set_content(html, wait_until="load")
            page.evaluate("document.fonts.ready")
            page.evaluate("""() => Promise.all([...document.images].map(i => i.decode()))""")
            _fit_dynamic_fields(page)
            _validate_layout(page)
            if page.locator('.canvas.report').count():
                from market_report_templates import validate_report_layout
                validate_report_layout(page)
            page.locator(".canvas").screenshot(path=str(target))
        finally:
            browser.close()


def render_png(kind: str, approved_text: str, output: Path | str, *, demo: bool = False, now: datetime | None = None) -> Path:
    """Render a verified rate card. Keep publisher's system Python unchanged."""
    import importlib.util
    import subprocess
    import sys

    html = html_for_post(kind, approved_text, now=now)
    if demo:
        # A visible test-only disclaimer inside image bytes; cannot be mistaken
        # for a live-price screenshot when forwarded without its Telegram caption.
        html = html.replace(
            "</style>",
            ".canvas{height:calc(var(--height) + 40px)}"
            ".demo-label{height:40px;flex-shrink:0;background:#9b1c1c;color:#fff;"
            "text-align:center;font-size:23px;line-height:40px;font-weight:800}</style>", 1)
        html = re.sub(r'(<div class="canvas [^\"]+">)',
                      r'\1<div class="demo-label">نمونه آزمایشی — قیمت‌ها واقعی نیستند</div>', html, count=1)
        if kind != "usdt":
            html = html.replace('.canvas{height:calc(var(--height) + 40px)}', '.canvas.report{height:calc(var(--height) + 40px)}')
            html = html.replace('.demo-label{height:40px;', '.demo-label{height:40px;background:#fff4db;color:#715015;border-bottom:1px solid #e6c991;')
            html = html.replace('background:#9b1c1c;color:#fff;', '')
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
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
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


def image_post_details(kind: str, approved_text: str, *, demo: bool = False) -> str | None:
    """Complete companion text for the mobile rate images, from the same snapshot.

    USDT's publisher header uses the exchange's SELL/BUY perspective. The image
    labels the customer's BUY/SELL perspective. Align only the display header;
    every source row, summary value and historical percentage remains untouched.
    """
    if kind not in SUPPORTED_MARKETS:
        return None
    text = approved_text
    if kind in {'fx-pulse','iran-gold','turkey-gold'}:
        from market_report_templates import parse_pulse,parse_iran_gold,parse_turkey_gold
        {'fx-pulse':parse_pulse,'iran-gold':parse_iran_gold,'turkey-gold':parse_turkey_gold}[kind](approved_text)
    if kind == 'usdt':
        _usdt(approved_text)  # Preserve strict source/summary validation.
        header = re.search(r'(<pre>)([^\n]*)(\n)', text)
        if header is None or unescape(header.group(2)).replace('\u200e','').split() != ['EXCHANGE','SELL','BUY','Δ24H','Δ1M']:
            raise ValueError('Unrecognized USDT publisher price/period columns')
        labels = '\u200e' + f"{'EXCHANGE':<9} {'BUY':>7} {'SELL':>7} {'Δ24H':>7} {'Δ1M':>7}"
        text = text[:header.start(2)] + labels + text[header.end(2):]
        text += ('\n\nخرید (BUY): مبلغ پرداختی شما برای خرید هر تتر.'
                 '\nفروش (SELL): مبلغ دریافتی شما از فروش هر تتر.')
    if demo:
        text = '🧪 <b>نمونه آزمایشی — قیمت‌ها واقعی نیستند</b>\n\n' + text
    return text


class IncompleteImagePostError(RuntimeError):
    """The photo exists; callers must inspect before retrying a partial delivery."""

    def __init__(self, photo_response: dict):
        self.photo_response = photo_response
        message_id = photo_response['result']['message_id']
        super().__init__(f'Photo message {message_id} was sent, but detail delivery was not confirmed. '
                         'Do not resend the photo; inspect the message before retrying details.')


def _telegram_text_length(text: str) -> int:
    # Conservative UTF-16 count after HTML entity parsing, including flags.
    visible = unescape(re.sub(r'<[^>]*>', '', text))
    return len(visible.encode('utf-16-le')) // 2


def _check_details_length(text: str) -> None:
    if not 1 <= _telegram_text_length(text) <= 4096:
        raise ValueError('Full market details must fit one Telegram text message; nothing sent')


def _telegram_send_details(token: str, chat_id: str, text: str, photo_id: int, timeout: int) -> dict:
    """Send the unchanged full HTML bulletin as a reply to its rate image."""
    payload = urlencode({
        'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML',
        'disable_notification': 'true', 'disable_web_page_preview': 'true',
        'reply_parameters': json.dumps({'message_id': photo_id}),
    }).encode('utf-8')
    request = Request(f'https://api.telegram.org/bot{token}/sendMessage', data=payload,
                      headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f'Telegram details HTTP {error.code}') from None
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f'Telegram details connection/response failure: {type(error).__name__}') from None
    if not result.get('ok') or not isinstance(result.get('result'), dict) or 'message_id' not in result['result']:
        raise RuntimeError('Telegram details did not return a message ID')
    return result


def telegram_send_photo(token: str, chat_id: str, photo: Path | str, caption: str, *,
                        timeout: int = 35, details_text: str | None = None,
                        details_as_caption: bool = False) -> dict:
    """Send a photo and optional complete bulletin; success requires both receipts.

    Requested short details fit directly in an HTML caption; longer bulletins
    use a linked text message. Full details are never truncated or retried.
    """
    if details_text is not None:
        _check_details_length(details_text)
    inline_details = details_text is not None and details_as_caption and _telegram_text_length(details_text) <= 1024
    boundary = "AlanChande" + uuid.uuid4().hex
    def field(name: str, val: str) -> bytes:
        return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n').encode()
    png = Path(photo).read_bytes()
    body = b"".join([field("chat_id",chat_id), field("caption",details_text if inline_details else caption[:1024]),
                     field("parse_mode","HTML") if inline_details else b"",
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
    if inline_details:
        result['details_in_caption'] = True
    elif details_text is not None:
        try:
            details = _telegram_send_details(token, chat_id, details_text, result['result']['message_id'], timeout)
        except Exception:
            raise IncompleteImagePostError(result) from None
        result['details_result'] = details['result']
    return result

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3 or sys.argv[1] != "--render-worker":
        raise SystemExit("Usage: market_images.py --render-worker OUTPUT.png")
    output = Path(sys.argv[2]).resolve()
    if not output.parent.is_dir():
        raise SystemExit("Output directory does not exist")
    _screenshot_html(sys.stdin.read(), output)

"""Render Instagram slides from customer quotes and assessed Telegram exports.

The Telegram publisher is invoked ONLY with --export-json. No Telegram messages,
history baselines, safety thresholds, or running bot processes are changed here.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

TEHRAN = ZoneInfo("Asia/Tehran")
ISTANBUL = ZoneInfo("Europe/Istanbul")
GREEN, INK, MUTED = "#298B6C", "#193E34", "#74877F"
BG, RULE, RED = "#F1F7F3", "#DCE8E0", "#BD534D"
FX_NAMES = {
    "USD": "دلار آمریکا", "EUR": "یورو", "GBP": "پوند انگلیس", "CHF": "فرانک سوئیس",
    "CAD": "دلار کانادا", "AUD": "دلار استرالیا", "SEK": "کرون سوئد", "NOK": "کرون نروژ",
    "RUB": "روبل روسیه", "THB": "بات تایلند", "SGD": "دلار سنگاپور", "HKD": "دلار هنگ کنگ",
    "AZN": "منات آذربایجان", "DKK": "کرون دانمارک", "AED": "درهم امارات", "TRY": "لیر ترکیه",
    "CNY": "یوان چین", "SAR": "ریال عربستان", "INR": "روپیه هند", "MYR": "رینگیت مالزی",
    "AFN": "افغانی افغانستان", "KWD": "دینار کویت", "BHD": "دینار بحرین", "OMR": "ریال عمان", "QAR": "ریال قطر",
}
HAWALA_CODES = ("USD", "EUR", "GBP", "CAD", "AUD", "SEK", "TRY")


class CarouselError(RuntimeError):
    pass


def _number(value, *, optional=False):
    if optional and value in {None, "—"}:
        return None
    try:
        result = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise CarouselError("Invalid numeric table cell") from exc
    if not result.is_finite() or result <= 0:
        raise CarouselError("Non-positive or non-finite table price")
    return result


def _change(value):
    if value == "—":
        return None
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?%", value):
        raise CarouselError("Invalid percentage table cell")
    return Decimal(value[:-1])


def _table(text, header):
    match = re.search(r"<pre>(.*?)</pre>", text, re.S)
    if match is None:
        raise CarouselError("Telegram export has no expected table")
    lines = html.unescape(match[1]).replace("\u200e", "").splitlines()
    lines = [line.strip() for line in lines if line.strip()]
    if not lines or lines[0].split() != header:
        raise CarouselError("Telegram table columns changed; refusing to guess their meaning")
    return lines[1:]


def _table_time(text):
    match = re.search(r"<code>(\d{2}:\d{2})</code>\s*تهران", text)
    if match is None:
        raise CarouselError("Telegram table has no Tehran timestamp")
    now = datetime.now(TEHRAN)
    hour, minute = (int(value) for value in match[1].split(":"))
    try:
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError as exc:
        raise CarouselError("Invalid Tehran timestamp") from exc
    # A collection spanning midnight may have finished on the following day.
    candidate = min((candidate - timedelta(days=1), candidate, candidate + timedelta(days=1)), key=lambda t: abs((now-t).total_seconds()))
    if not -60 <= (now - candidate).total_seconds() <= 300:
        raise CarouselError("Telegram table is too old for this collection")
    return candidate.isoformat()


def _parse_usdt(text):
    rows = []
    for line in _table(text, ["EXCHANGE", "SELL", "BUY", "Δ24H", "Δ1M"]):
        cells = line.split()
        if len(cells) != 5 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", cells[0]):
            raise CarouselError("Unexpected exchange table row")
        ask, bid = _number(cells[1]), _number(cells[2], optional=True)
        if bid is not None and bid >= ask:
            raise CarouselError("Crossed exchange buy/sell pair")
        rows.append({"name": cells[0], "ask": str(ask), "bid": str(bid) if bid else None,
                     "day": str(_change(cells[3])) if cells[3] != "—" else None,
                     "month": str(_change(cells[4])) if cells[4] != "—" else None})
    if not 2 <= len(rows) <= 7 or len({row["name"] for row in rows}) != len(rows):
        raise CarouselError("Unexpected exchange coverage")
    return {"kind": "usdt", "rows": rows, "generated_at": _table_time(text)}


def _parse_fx(text):
    rows = {}
    for line in _table(text, ["CURRENCY", "TOMAN", "Δ24H", "Δ1M"]):
        # Country flags are decorative; read the explicit currency code instead.
        match = re.search(r"\b([A-Z]{3})\s+([\d,]+)\s+(\S+)\s+(\S+)\s*$", line)
        if match is None:
            raise CarouselError("Unexpected FX table row")
        code, price, day, month = match.groups()
        if code not in FX_NAMES or code in rows:
            raise CarouselError("Unknown or duplicate FX currency")
        rows[code] = {"code": code, "price": str(_number(price)),
                      "day": str(_change(day)) if day != "—" else None,
                      "month": str(_change(month)) if month != "—" else None}
    if set(rows) != set(FX_NAMES):
        raise CarouselError("The FX export does not contain the complete currency board")
    return {"kind": "fx", "rows": [rows[code] for code in FX_NAMES], "generated_at": _table_time(text)}


def _export(repo, post):
    script = repo / "channel_split/publish_channels.py"
    history = Path(os.getenv("INSTAGRAM_MARKET_HISTORY_DB", str(repo / "channel_split/market_history_production.sqlite3"))).expanduser()
    if not script.is_file() or not history.is_file():
        raise CarouselError("Production Telegram publisher or market history is missing")
    environment = dict(os.environ, MARKET_SAFETY_MODE="enforce", PYTHONIOENCODING="utf-8")
    try:
        # Like the existing X bridge, assess against a consistent read-only
        # backup. Collector schema initialization cannot alter production DBs.
        with tempfile.TemporaryDirectory(prefix="kiani-instagram-history-") as tmp:
            snapshot = Path(tmp) / "history.sqlite3"
            with closing(sqlite3.connect(history.resolve().as_uri()+"?mode=ro", uri=True, timeout=3)) as source:
                with closing(sqlite3.connect(snapshot)) as target:
                    source.backup(target)
            environment["MARKET_HISTORY_DB"] = str(snapshot)
            result = subprocess.run(
                [os.getenv("INSTAGRAM_TELEGRAM_PYTHON", "/usr/bin/python3"), str(script), "--post", post, "--export-json"],
                cwd=script.parent, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=180, check=False,
            )
    except (OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
        raise CarouselError("Telegram collection unavailable (" + type(exc).__name__ + ")") from exc
    if result.returncode:
        # Collector logs can contain credentials from external libraries. Do not
        # relay raw stderr into the public publisher's log or caption.
        raise CarouselError(f"Telegram assessed export failed (exit {result.returncode}); inspect its production source-health log")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CarouselError("Telegram publisher did not return a JSON export") from exc
    if not isinstance(payload, dict) or payload.get("post") != post or payload.get("verified") is not True or not isinstance(payload.get("text"), str):
        raise CarouselError("Telegram export is not verified")
    return payload["text"]


def _hawala_snapshot():
    configured = os.getenv("INSTAGRAM_HAWALA_SNAPSHOT", "").strip()
    if not configured:
        raise CarouselError("Set INSTAGRAM_HAWALA_SNAPSHOT to the existing successful Telegram delivery export")
    try:
        payload = json.loads(Path(configured).expanduser().read_text(encoding="utf-8"))
        generated = datetime.fromisoformat(payload["generated_at"])
        raw = payload["rates"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CarouselError("Hawala snapshot is missing or invalid") from exc
    if not isinstance(payload, dict) or not isinstance(raw, dict):
        raise CarouselError("Hawala snapshot must contain a rates object")
    if payload.get("source") != "kiani-hawala" or generated.tzinfo is None:
        raise CarouselError("Hawala snapshot lacks trusted provenance or timezone")
    age = (datetime.now(timezone.utc) - generated).total_seconds()
    if not -60 <= age <= 900:
        raise CarouselError("Hawala Telegram snapshot is older than 15 minutes")
    rows = []
    for code in HAWALA_CODES:
        if code not in raw:
            raise CarouselError("Hawala snapshot lacks " + code)
        value = _number(raw[code])
        if value != value.to_integral_value():
            raise CarouselError("Hawala snapshot contains fractional Toman")
        rows.append({"code": code, "price": str(value)})
    return {"kind": "hawala", "rows": rows, "generated_at": generated.isoformat()}


def collect_sections():
    repo = Path(os.getenv("INSTAGRAM_TELEGRAM_REPO", "/home/kianirad2020/telegram_bot_repo")).expanduser().resolve()
    tasks = (
        ("usdt", lambda: _parse_usdt(_export(repo, "alanchande-usdt-exchanges"))),
        ("fx", lambda: _parse_fx(_export(repo, "alanchande-iran-fx"))),
        ("hawala", _hawala_snapshot),
    )
    sections = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [(kind, pool.submit(task)) for kind, task in tasks]
        for kind, future in futures:
            try:
                section = future.result()
                sections.append(section)
            except CarouselError as exc:
                print(f"Carousel section omitted: {kind}: {exc}", file=sys.stderr, flush=True)
    fresh = []
    for section in sections:
        maximum = 900 if section["kind"] == "hawala" else 300
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(section["generated_at"])).total_seconds()
        if -60 <= age <= maximum:
            fresh.append(section)
        else:
            print(f"Carousel section omitted: {section['kind']}: expired while collecting", file=sys.stderr, flush=True)
    return fresh


def assert_fresh_sections(sections):
    for section in sections:
        maximum = 900 if section["kind"] == "hawala" else 300
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(section["generated_at"])).total_seconds()
        if not -60 <= age <= maximum:
            raise CarouselError("Carousel section expired before publishing: " + section["kind"])


def sample_bundle():
    path = Path(__file__).parent / "deploy/instagram-rates/carousel-sample.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {key: Decimal(str(value)) for key, value in payload["customer_rates"].items()}, payload["sections"]


def render_carousel(ig, rates, sections, moment, directory, *, sample=False):
    """Render the approved RTL Feed design with bundled fonts and artwork."""
    from PIL import ImageFilter

    root = Path(__file__).resolve().parent
    bold_path = root / "fonts/Vazirmatn-Bold.ttf"
    asset_dir = root / "assets/instagram"
    if not bold_path.is_file() or not (asset_dir / "icons.png").is_file() or not (asset_dir / "icons.json").is_file():
        raise CarouselError("Restore fonts/Vazirmatn-Bold.ttf and assets/instagram for the carousel design")
    with Image.open(asset_dir / "icons.png") as opened:
        atlas = opened.convert("RGBA")
    artwork = json.loads((asset_dir / "icons.json").read_text(encoding="utf-8"))
    font_cache, icon_cache = {}, {}
    directory.mkdir(parents=True, exist_ok=True)
    green, ink, muted = "#1C8C67", "#173D32", "#6D827A"
    background, rule, red, blue = "#EDF4F0", "#D6E4DC", "#D33226", "#307DAA"

    def font(size, bold=False):
        key = (size, bold)
        if key not in font_cache:
            font_cache[key] = ImageFont.truetype(str(bold_path) if bold else ig._font_path(), size, layout_engine=ImageFont.Layout.BASIC)
        return font_cache[key]

    def fa(draw, text, xy, size=32, fill=ink, anchor="mm", bold=False):
        ig._draw_rtl(draw, text, xy, font(size, bold), fill, anchor=anchor)

    def latin(draw, text, xy, size=32, fill=ink, anchor="mm", bold=False):
        draw.text(xy, str(text), font=font(size, bold), fill=fill, anchor=anchor)

    def icon(image, key, xy, size=40):
        cache_key = (key, size)
        if cache_key not in icon_cache:
            icon_cache[cache_key] = atlas.crop(artwork[key]["box"]).resize((size, size), Image.Resampling.LANCZOS)
        image.paste(icon_cache[cache_key], (round(xy[0]-size/2), round(xy[1]-size/2)), icon_cache[cache_key])

    def title(image, text, xy, size=58, key=None, fill=ink, bold=True, icon_size=None, left_key=None):
        draw = ImageDraw.Draw(image)
        rendered = ig._rtl(text)
        while size > 22 and draw.textlength(rendered, font=font(size, bold)) + (size+22 if key else 0) + (size+22 if left_key else 0) > 942:
            size -= 1
        width = draw.textlength(rendered, font=font(size, bold))
        pictogram = icon_size or size
        full = width + pictogram + 18 if key else width
        if left_key:
            full += pictogram + 18
        left = xy[0]-full/2
        if left_key:
            icon(image, left_key, (left+pictogram/2, xy[1]), pictogram)
            left += pictogram+18
        fa(draw, text, (left+width/2, xy[1]), size, fill, bold=bold)
        if key:
            icon(image, key, (left+width+18+pictogram/2, xy[1]), pictogram)

    def card(image, box, *, stripe=None, shadow=False, radius=30):
        if shadow:
            layer = Image.new("RGBA", image.size)
            sd = ImageDraw.Draw(layer)
            x1, y1, x2, y2 = box
            sd.rounded_rectangle((x1, y1+10, x2, y2+10), radius=radius, fill=(30, 60, 48, 18))
            image.paste(Image.alpha_composite(image.convert("RGBA"), layer.filter(ImageFilter.GaussianBlur(12))).convert("RGB"))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(box, radius=radius, fill=stripe or "#FFFFFF")
        if stripe:
            x1, y1, x2, y2 = box
            draw.rounded_rectangle((x1, y1, x2-12, y2), radius=radius, fill="#FFFFFF")

    def amount(value):
        return "—" if value is None else f"{int(Decimal(str(value)).quantize(Decimal('1'))):,}"

    def percent(draw, value, xy):
        if value is None:
            latin(draw, "—", xy, 26, muted)
            return
        change = Decimal(str(value))
        color = green if change > 0 else red if change < 0 else muted
        label = f"{change:+.2f}%"
        width = draw.textlength(label, font=font(25))
        left = xy[0]-(width+24)/2
        cx, cy = left+6, xy[1]
        if change > 0:
            draw.polygon(((cx-7, cy+6), (cx+7, cy+6), (cx, cy-7)), fill=color)
        elif change < 0:
            draw.polygon(((cx-7, cy-6), (cx+7, cy-6), (cx, cy+7)), fill=color)
        else:
            draw.ellipse((cx-5, cy-5, cx+5, cy+5), fill=color)
        latin(draw, label, (left+24, cy), 25, color, anchor="lm")

    def currency(image, code, xy, size=34):
        draw = ImageDraw.Draw(image)
        width = draw.textlength(code, font=font(size, True))
        full = 48+14+width
        left = xy[0]-full/2
        icon(image, code, (left+24, xy[1]), 48)
        latin(draw, code, (left+62, xy[1]), size, green, anchor="lm", bold=True)

    def timestamp(image, stamp, y=1230, customer=False):
        t = datetime.fromisoformat(stamp).astimezone(ISTANBUL if customer else TEHRAN)
        zone = "استانبول" if customer else "تهران"
        title(image, f"{t:%Y/%m/%d} · {t:%H:%M} {zone}", (540, y), 26,
              "location" if customer else "clock", muted, False, 28)

    def base(heading, subtitle, stamp, key, *, customer=False, rule_y=1144, stamp_y=1230, left_key=None):
        image = Image.new("RGB", (1080, 1350), background)
        draw = ImageDraw.Draw(image)
        latin(draw, "kiani.exchange", (64, 137), 34, anchor="lm", bold=True)
        fa(draw, "صرافی کیانی", (976, 137), 34, anchor="rm", bold=True)
        icon(image, "exchange", (1003, 137), 36)
        title(image, heading, (540, 237), 60, key, left_key=left_key)
        fa(draw, subtitle, (540, 306), 30, muted)
        draw.line((64, rule_y, 1016, rule_y), fill=rule, width=2)
        if stamp:
            timestamp(image, stamp, stamp_y, customer)
        return image, draw

    frames, included, footer_positions = [], [], {}

    def tether(draw, xy, size):
        # Vazirmatn does not contain U+20AE. Draw the Tether badge as geometry
        # instead of relying on an unavailable OS/font fallback.
        x, y = xy
        scale = size/40
        draw.rectangle((x-12*scale, y-13*scale, x+12*scale, y-8*scale), fill="#FFFFFF")
        draw.rectangle((x-3*scale, y-8*scale, x+3*scale, y+14*scale), fill="#FFFFFF")
        draw.ellipse((x-18*scale, y-3*scale, x+18*scale, y+4*scale), outline="#FFFFFF", width=max(1, round(2*scale)))
    # The Feed cover has its own approved layout; the Story renderer is unchanged.
    image = Image.new("RGB", (1080, 1350), background)
    draw = ImageDraw.Draw(image)
    draw.ellipse((502, 114, 578, 190), fill="#D6EBE1")
    latin(draw, "K", (540, 153), 42, green, bold=True)
    title(image, "صرافی کیانی", (540, 239), 68, "exchange", icon_size=72)
    title(image, "نرخ امروز", (540, 316), 32, "chart", muted, False, 30)
    for box, label, keys, badge in (
        ((64, 354, 1016, 594), "لیر ترکیه", ("buy_lira", "sell_lira"), "TRY"),
        ((64, 614, 1016, 854), "تتر (USDT)", ("buy_usdt", "sell_usdt"), "tether"),
    ):
        card(image, box, shadow=True)
        draw = ImageDraw.Draw(image)
        top = box[1]
        fa(draw, label, (907, top+46), 42, anchor="rm", bold=True)
        draw.ellipse((922, top+20, 978, top+76), fill="#EB001B" if badge == "TRY" else "#25A17C")
        if badge == "TRY":
            # A circular Turkish badge drawn directly avoids a clipped rectangular flag.
            draw.ellipse((934, top+33, 962, top+61), fill="#FFFFFF")
            draw.ellipse((940, top+31, 966, top+57), fill="#EB001B")
            import math
            draw.polygon([(968+math.cos(-math.pi/2+i*math.pi/5)*(6 if i % 2 == 0 else 2.5),
                           top+49+math.sin(-math.pi/2+i*math.pi/5)*(6 if i % 2 == 0 else 2.5)) for i in range(10)], fill="#FFFFFF")
        else:
            tether(draw, (950, top+49), 34)
        for offset, text, key, dot in ((114, "از ما می‌خرید", keys[0], "#79B254"), (187, "به ما می‌فروشید", keys[1], "#51A9EA")):
            y = top+offset
            draw.ellipse((948, y-15, 978, y+15), fill=dot)
            fa(draw, text, (931, y), 36, anchor="rm")
            fa(draw, ig._persian_number(rates[key]), (161, y), 54, anchor="lm", bold=True)
            fa(draw, "تومان", (151, y+8), 25, muted, anchor="rm")
    card(image, (64, 874, 1016, 1060), shadow=True)
    draw = ImageDraw.Draw(image)
    title(image, "نرخ تبدیل", (540, 910), 36, "convert", muted, False, 34)
    for y, text, key, right_flag, other in (
        (963, "لیر به تتر", "lira_to_usdt", True, False),
        (1017, "تتر به لیر", "usdt_to_lira", False, True),
    ):
        fa(draw, text, (930, y), 34, anchor="rm")
        if right_flag:
            icon(image, "TRY", (961, y), 34)
        else:
            draw.ellipse((946, y-15, 976, y+15), fill="#25A17C")
            tether(draw, (961, y), 19)
        if other:
            icon(image, "TRY", (797, y), 34)
        else:
            draw.ellipse((778, y-15, 808, y+15), fill="#25A17C")
            tether(draw, (793, y), 19)
        fa(draw, ig._persian_number(rates[key], decimals=2)+" لیر", (106, y), 42, anchor="lm", bold=True)
    local = moment.astimezone(ISTANBUL)
    title(image, f"{local:%H:%M} · استانبول", (540, 1103), 30, "location", muted, False, 30)
    title(image, "سفارش: لینک در Bio", (540, 1260), 46, "down", green, True, 46)
    frames.append(image)

    for section in sections:
        kind, rows, stamp = section["kind"], section["rows"], section["generated_at"]
        if kind == "usdt":
            image, draw = base("تتر در صرافی‌های ایران", "قیمت یک تتر به تومان · نرخ‌های اطلاع‌رسانی", stamp, "IRAN", rule_y=1192)
            columns = (886, 652, 452, 266, 115)
            for label, x in zip(("صرافی", "خرید شما", "فروش شما", "۲۴ ساعت", "۱ ماه"), columns):
                fa(draw, label, (x, 375), 26, muted, bold=True)
            # Seven providers fit the same summary area without reducing the type.
            step = 87 if len(rows) <= 6 else 75
            for i, row in enumerate(rows):
                y = 443+i*step
                draw.rounded_rectangle((64, y-39, 1016, y+40), radius=16, fill="#FFFFFF" if i % 2 == 0 else "#E5EFE8")
                latin(draw, row["name"], (columns[0], y), 32, bold=True)
                latin(draw, amount(row["ask"]), (columns[1], y), 33, green, bold=True)
                latin(draw, amount(row["bid"]), (columns[2], y), 33)
                percent(draw, row.get("day"), (columns[3], y))
                percent(draw, row.get("month"), (columns[4], y))
            asks = [Decimal(row["ask"]) for row in rows]
            bids = [Decimal(row["bid"]) for row in rows if row["bid"] is not None]
            for box, text, value, color, key in (
                ((552, 964, 1016, 1130), "میانگین خرید شما", sum(asks)/len(asks), green, "cart"),
                ((64, 964, 528, 1130), "میانگین فروش شما", sum(bids)/len(bids) if bids else None, ink, "money"),
            ):
                card(image, box, radius=20)
                cx = (box[0]+box[2])/2
                title(image, text, (cx, 1007), 29, key, muted, False, 30)
                draw = ImageDraw.Draw(image)
                latin(draw, amount(value), (cx, 1068), 56, color, bold=True)
            cheapest = min(rows, key=lambda row: Decimal(row["ask"]))
            selling = [row for row in rows if row["bid"] is not None]
            highest = max(selling, key=lambda row: Decimal(row["bid"])) if selling else None
            for cx, label, row, key in ((784, "کمترین قیمت خرید", cheapest, "ask"), (296, "بیشترین قیمت فروش", highest, "bid")):
                name = row["name"]+" "+amount(row[key]) if row else "—"
                size = 26
                def summary_width():
                    return draw.textlength(name, font=font(size, True))+draw.textlength(ig._rtl(label), font=font(size))+48
                while size > 18 and summary_width() > 440:
                    size -= 1
                left = cx-summary_width()/2
                latin(draw, name, (left, 1165), size, anchor="lm", bold=True)
                left += draw.textlength(name, font=font(size, True))+12
                fa(draw, label, (left, 1165), size, muted, anchor="lm")
                left += draw.textlength(ig._rtl(label), font=font(size))+20
                icon(image, "trophy", (left, 1165), 26)
            frames.append(image)
            included.append("مقایسه تتر در صرافی‌های ایران")
        elif kind == "fx":
            pages = [rows[index:index+9] for index in range(0, len(rows), 9)]
            for number, page in enumerate(pages, 1):
                image, draw = base("نرخ ارز آزاد ایران", f"واحد: تومان · بازار آزاد · بخش {number} از {len(pages)}", stamp, f"globe{number}")
                columns = (885, 658, 448, 262, 114)
                for label, x in zip(("ارز", "نام ارز", "تومان", "۲۴ ساعت", "۱ ماه"), columns):
                    fa(draw, label, (x, 375), 26, muted, bold=True)
                for i, row in enumerate(page):
                    y = 438+i*77
                    draw.rounded_rectangle((64, y-35, 1016, y+35), radius=16, fill="#FFFFFF" if i % 2 == 0 else "#E5EFE8")
                    currency(image, row["code"], (columns[0], y))
                    name = FX_NAMES[row["code"]]
                    size = 30
                    while size > 22 and draw.textlength(ig._rtl(name), font=font(size)) > 250:
                        size -= 1
                    fa(draw, name, (columns[1], y), size)
                    latin(draw, amount(row["price"]), (columns[2], y), 34, bold=True)
                    percent(draw, row.get("day"), (columns[3], y))
                    percent(draw, row.get("month"), (columns[4], y))
                title(image, "نرخ‌ها صرفاً جهت اطلاع‌رسانی است", (540, 1180), 27, "info", muted, False, 26)
                frames.append(image)
            included.append("نرخ ارز بازار آزاد ایران")
        elif kind == "hawala":
            image, draw = base("نرخ حواله به ایران", "", stamp, "flying_money", rule_y=1073, stamp_y=1278, left_key="IRAN")
            title(image, "پرداخت به تومان · قبل از واریز هماهنگ کنید", (540, 305), 29, "phone", muted, False, 28)
            for i, row in enumerate(rows):
                y = 416+i*100
                draw.rounded_rectangle((64, y-44, 1016, y+44), radius=16, fill="#FFFFFF" if i % 2 == 0 else "#E5EFE8")
                currency(image, row["code"], (818, y), 38)
                fa(draw, FX_NAMES[row["code"]], (553, y), 34)
                latin(draw, amount(row["price"]), (87, y), 43, anchor="lm", bold=True)
            title(image, "نرخ لحظه‌ای و سایر ارزها در ربات تلگرام صرافی کیانی", (540, 1110), 26, "robot", muted, False, 28)
            # An explicit platform label and full URL help Instagram readers
            # identify where to open the bot; image text itself is not clickable.
            prefix, handle, address = "Telegram · ", "@kianiexchangebot", "https://t.me/kianiexchangebot"
            prefix_width = draw.textlength(prefix, font=font(28))
            line_width = prefix_width+draw.textlength(handle, font=font(28, True))
            address_width = draw.textlength(address, font=font(26, True))
            panel_width = max(line_width, address_width)+118
            left, right = 540-panel_width/2, 540+panel_width/2
            draw.rounded_rectangle((left, 1142, right, 1246), radius=22, fill="#FFFFFF", outline="#C4E6FB", width=2)
            logo_x, logo_y = left+49, 1194
            draw.ellipse((logo_x-32, logo_y-32, logo_x+32, logo_y+32), fill="#2AABEE")
            # Draw the Telegram paper-plane mark without an OS emoji dependency.
            draw.polygon(((logo_x-20, logo_y-2), (logo_x+19, logo_y-15), (logo_x+11, logo_y+19), (logo_x, logo_y+9), (logo_x-7, logo_y+15), (logo_x-6, logo_y+3)), fill="#FFFFFF")
            draw.polygon(((logo_x-6, logo_y+3), (logo_x+12, logo_y-8), (logo_x, logo_y+9)), fill="#2AABEE")
            text_x = left+100
            latin(draw, prefix, (text_x, 1176), 28, anchor="lm")
            latin(draw, handle, (text_x+prefix_width, 1176), 28, "#1594DA", anchor="lm", bold=True)
            latin(draw, address, (text_x, 1216), 26, muted, anchor="lm", bold=True)
            footer_positions[len(frames)+1] = 1322
            frames.append(image)
            included.append("حواله به ایران")

    image, draw = base("نرخ لیر ترکیه", "نرخ مشتری صرافی کیانی · تومان برای هر لیر", moment.isoformat(), "TRY", customer=True, rule_y=1220, stamp_y=1258)
    for box, label, key, color, symbol in (
        ((64, 367, 1016, 653), "خرید لیر از ما", "buy_lira", green, "cart"),
        ((64, 693, 1016, 979), "فروش لیر به ما", "sell_lira", blue, "money"),
    ):
        card(image, box, stripe=color, shadow=True)
        title(image, label, (540, box[1]+72), 42, symbol, ink, True, 40)
        draw = ImageDraw.Draw(image)
        latin(draw, amount(rates[key]), (540, box[1]+182), 130, color, bold=True)
    title(image, "لطفاً قبل از واریز هماهنگ کنید", (540, 1055), 41, "warning", ink, True, 38)
    for y, label, value, key in (
        (1134, "Telegram: ", "t.me/TL905411603664", "plane"),
        (1191, "WhatsApp: ", "+90 539 290 56 86", "chat"),
    ):
        width1 = draw.textlength(label, font=font(36))
        width2 = draw.textlength(value, font=font(36, True))
        left = (1080-width1-width2-46)/2
        icon(image, key, (left+16, y), 34)
        latin(draw, label, (left+46, y), 36, green, anchor="lm")
        latin(draw, value, (left+46+width1, y), 36, green, anchor="lm", bold=True)
    frames.append(image)

    if not 2 <= len(frames) <= 10:
        raise CarouselError("Rendered carousel exceeds the supported item count")
    digest = hashlib.sha256(json.dumps({"rates": rates, "sections": sections}, default=str, sort_keys=True).encode()).hexdigest()[:10]
    paths = []
    for index, image in enumerate(frames, 1):
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((64, 76, 1016, 88), radius=6, fill=rule)
        draw.rounded_rectangle((1016-round(952*index/len(frames)), 76, 1016, 88), radius=6, fill=green)
        latin(draw, f"{index} / {len(frames)}", (64, 1282), 27, muted, anchor="lm")
        if index == len(frames):
            title(image, "صرافی کیانی", (540, 1305), 30, "handshake", green, False, 28)
        elif index > 1:
            footer_y = footer_positions.get(index, 1282)
            title(image, "صرافی کیانی · ورق بزنید", (540, footer_y), 30, "next", green, False, 30)
        if sample:
            draw.rectangle((0, 0, 1080, 54), fill="#A77221")
            fa(draw, "نمونه برای بررسی طرح · نرخ لحظه‌ای نیست", (540, 27), 27, "#FFFFFF", bold=True)
        name = f"kiani-carousel-{moment.astimezone(ISTANBUL):%Y-%m-%d-%H%M%S}-{digest}-{index:02}.jpg"
        path = directory / name
        image.save(path, "JPEG", quality=94, optimize=True)
        paths.append(path)
    caption = ig.build_caption(rates, moment) + "\n\nورق بزنید: نرخ مشتری لیر"
    if included:
        caption += "، " + "، ".join(included)
    caption += "\nنرخ بازار و صرافی‌های دیگر صرفاً جهت اطلاع‌رسانی است و با نرخ مشتری کیانی تفاوت دارد.\nلطفاً قبل از واریز هماهنگ کنید."
    caption += "\nIcons: Twemoji by Twitter and contributors · CC BY 4.0: https://creativecommons.org/licenses/by/4.0/"
    if sample:
        caption = "نمونه برای بررسی طرح؛ این نرخ‌ها لحظه‌ای نیستند و قابل انتشار نیستند.\n\n" + caption
    manifest = {"sample": sample, "generated_at": moment.isoformat(), "slides": [str(path) for path in paths], "sections": sections, "customer_rates": rates, "caption": caption}
    (directory / (paths[0].stem.rsplit("-", 1)[0] + ".json")).write_text(json.dumps(manifest, default=str, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return paths, caption

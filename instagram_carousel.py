"""Render Instagram slides from customer quotes and assessed Telegram exports.

The Telegram publisher is invoked ONLY with --export-json. No Telegram messages,
history baselines, safety thresholds, or running bot processes are changed here.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import html
import json
import os
from pathlib import Path
import re
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
    environment = dict(os.environ, MARKET_HISTORY_DB=str(history.resolve()), MARKET_SAFETY_MODE="enforce", PYTHONIOENCODING="utf-8")
    try:
        result = subprocess.run(
            [os.getenv("INSTAGRAM_TELEGRAM_PYTHON", "/usr/bin/python3"), str(script), "--post", post, "--export-json"],
            cwd=script.parent, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=180, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
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
                # Recheck after the other collectors finish, not just on read.
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(section["generated_at"])).total_seconds()
                if age > 900:
                    raise CarouselError("Section expired while collecting")
                sections.append(section)
            except CarouselError as exc:
                print(f"Carousel section omitted: {kind}: {exc}", file=sys.stderr, flush=True)
    return sections


def sample_bundle():
    path = Path(__file__).parent / "deploy/instagram-rates/carousel-sample.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {key: Decimal(str(value)) for key, value in payload["customer_rates"].items()}, payload["sections"]


def render_carousel(ig, rates, sections, moment, directory, *, sample=False):
    """Render a cover, optional market sections, and a customer TRY/contact card."""
    font_path = ig._font_path()
    fonts = {size: ImageFont.truetype(font_path, size, layout_engine=ImageFont.Layout.BASIC) for size in (24, 28, 30, 32, 34, 38, 42, 48, 58, 76)}
    directory.mkdir(parents=True, exist_ok=True)

    def fa(draw, text, xy, size=32, fill=INK, anchor="mm"):
        ig._draw_rtl(draw, text, xy, fonts[size], fill, anchor=anchor)

    def latin(draw, text, xy, size=32, fill=INK, anchor="mm"):
        draw.text(xy, text, font=fonts[size], fill=fill, anchor=anchor)

    def amount(value):
        return "—" if value is None else f"{int(Decimal(str(value)).quantize(Decimal('1'))):,}"

    def percent(value):
        return "—" if value is None else f"{Decimal(str(value)):+.2f}%"

    def pct_color(value):
        return MUTED if value is None or Decimal(str(value)) == 0 else (GREEN if Decimal(str(value)) > 0 else RED)

    def base(title, subtitle, stamp, *, customer=False):
        image = Image.new("RGB", (1080, 1350), BG)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((54, 44, 1026, 54), radius=5, fill=RULE)
        draw.rounded_rectangle((54, 44, 255, 54), radius=5, fill=GREEN)
        latin(draw, "kiani.exchange", (64, 102), 38, anchor="lm")
        fa(draw, "صرافی کیانی", (1016, 102), 32, anchor="rm")
        fa(draw, title, (540, 220), 58)
        fa(draw, subtitle, (540, 288), 30, MUTED)
        draw.line((72, 1182, 1008, 1182), fill=RULE, width=2)
        if stamp:
            t = datetime.fromisoformat(stamp).astimezone(ISTANBUL if customer else TEHRAN)
            zone_name = "استانبول" if customer else "تهران"
            fa(draw, f"{t:%Y/%m/%d} · {t:%H:%M} {zone_name}", (540, 1215), 28, MUTED)
        return image, draw

    frames = []
    handle, name = tempfile.mkstemp(prefix=".carousel-cover-", suffix=".jpg", dir=directory)
    os.close(handle)
    cover = Path(name)
    try:
        ig.render_banner(rates, moment, "feed", cover)
        with Image.open(cover) as opened:
            frames.append(opened.convert("RGB"))
    finally:
        cover.unlink(missing_ok=True)
    included = []
    for section in sections:
        kind = section["kind"]
        rows = section["rows"]
        stamp = section["generated_at"]
        if kind == "usdt":
            image, draw = base("تتر در صرافی‌های ایران", "قیمت یک تتر به تومان · نرخ‌های اطلاع‌رسانی", stamp)
            x = (170, 390, 595, 790, 943)
            for label, cx in zip(("صرافی", "خرید شما", "فروش شما", "۲۴ ساعت", "۱ ماه"), x):
                fa(draw, label, (cx, 357), 28)
            for i, row in enumerate(rows):
                y = 434 + i * 74
                draw.rounded_rectangle((64, y-31, 1016, y+32), radius=14, fill="#FFFFFF" if i % 2 == 0 else "#E7F0EA")
                latin(draw, row["name"], (x[0], y), 28)
                latin(draw, amount(row["ask"]), (x[1], y), 32, GREEN)
                latin(draw, amount(row["bid"]), (x[2], y), 32)
                for cx, key in zip(x[3:], ("day", "month")):
                    latin(draw, percent(row.get(key)), (cx, y), 24, pct_color(row.get(key)))
            asks = [Decimal(row["ask"]) for row in rows]
            bids = [Decimal(row["bid"]) for row in rows if row["bid"] is not None]
            fa(draw, "میانگین خرید شما", (780, 968), 28, MUTED)
            fa(draw, "میانگین فروش شما", (310, 968), 28, MUTED)
            latin(draw, amount(sum(asks)/len(asks)), (780, 1016), 42, GREEN)
            latin(draw, amount(sum(bids)/len(bids)) if bids else "—", (310, 1016), 42)
            cheapest = min(rows, key=lambda row: Decimal(row["ask"]))
            fa(draw, "کمترین قیمت خرید", (825, 1080), 28, MUTED)
            latin(draw, cheapest["name"] + "  " + amount(cheapest["ask"]), (345, 1080), 28)
            selling = [row for row in rows if row["bid"] is not None]
            if selling:
                highest = max(selling, key=lambda row: Decimal(row["bid"]))
                fa(draw, "بیشترین قیمت فروش", (825, 1136), 28, MUTED)
                latin(draw, highest["name"] + "  " + amount(highest["bid"]), (345, 1136), 28)
            frames.append(image)
            included.append("مقایسه تتر در صرافی‌های ایران")
        elif kind == "fx":
            pages = [rows[index:index+9] for index in range(0, len(rows), 9)]
            for number, page in enumerate(pages, 1):
                image, draw = base("نرخ ارز آزاد ایران", f"واحد: تومان · بازار آزاد · بخش {number} از {len(pages)}", stamp)
                x = (132, 358, 631, 811, 956)
                for label, cx in zip(("ارز", "نام ارز", "تومان", "۲۴ ساعت", "۱ ماه"), x):
                    fa(draw, label, (cx, 362), 28)
                for i, row in enumerate(page):
                    y = 440 + i * 77
                    draw.rounded_rectangle((64, y-32, 1016, y+33), radius=14, fill="#FFFFFF" if i % 2 == 0 else "#E7F0EA")
                    latin(draw, row["code"], (x[0], y), 32, GREEN)
                    fa(draw, FX_NAMES[row["code"]], (x[1], y), 28)
                    latin(draw, amount(row["price"]), (x[2], y), 32)
                    for cx, key in zip(x[3:], ("day", "month")):
                        latin(draw, percent(row.get(key)), (cx, y), 24, pct_color(row.get(key)))
                fa(draw, "نرخ‌ها صرفاً جهت اطلاع‌رسانی است", (540, 1150), 28, MUTED)
                frames.append(image)
            included.append("نرخ ارز بازار آزاد ایران")
        elif kind == "hawala":
            image, draw = base("نرخ حواله به ایران", "پرداخت به تومان · قبل از واریز هماهنگ کنید", stamp)
            for i, row in enumerate(rows):
                y = 412 + i * 91
                draw.rounded_rectangle((72, y-36, 1008, y+37), radius=16, fill="#FFFFFF")
                latin(draw, row["code"], (145, y), 34, GREEN)
                fa(draw, FX_NAMES[row["code"]], (500, y), 34)
                latin(draw, amount(row["price"]), (866, y), 38)
            fa(draw, "نرخ لحظه‌ای و سایر ارزها", (540, 1090), 28, MUTED)
            latin(draw, "@Kianiexchangebot", (540, 1138), 34, GREEN)
            frames.append(image)
            included.append("حواله به ایران")

    image, draw = base("نرخ لیر ترکیه", "نرخ مشتری صرافی کیانی · تومان برای هر لیر", moment.isoformat(), customer=True)
    for y, label, key, color in ((464, "خرید لیر از ما", "buy_lira", GREEN), (734, "فروش لیر به ما", "sell_lira", "#3B86A6")):
        draw.rounded_rectangle((92, y-110, 988, y+115), radius=30, fill="#FFFFFF")
        fa(draw, label, (540, y-45), 42, color)
        latin(draw, amount(rates[key]), (540, y+35), 76, color)
    fa(draw, "لطفاً قبل از واریز هماهنگ کنید", (540, 945), 34)
    latin(draw, "Telegram: t.me/TL905411603664", (540, 1025), 32, GREEN)
    latin(draw, "WhatsApp: +90 539 290 56 86", (540, 1080), 32, GREEN)
    frames.append(image)
    if not 2 <= len(frames) <= 10:
        raise CarouselError("Rendered carousel exceeds the supported item count")
    digest = hashlib.sha256(json.dumps({"rates": rates, "sections": sections}, default=str, sort_keys=True).encode()).hexdigest()[:10]
    paths = []
    for index, image in enumerate(frames, 1):
        draw = ImageDraw.Draw(image)
        latin(draw, f"{index} / {len(frames)}", (972, 1289), 28, MUTED)
        if index > 1:
            fa(draw, "صرافی کیانی · ورق بزنید", (416, 1289), 28, GREEN)
        if sample:
            draw.rectangle((0, 0, 1080, 39), fill="#A66D18")
            fa(draw, "نمونه برای بررسی طرح · نرخ لحظه‌ای نیست", (540, 20), 24, "#FFFFFF")
        name = f"kiani-carousel-{moment.astimezone(ISTANBUL):%Y-%m-%d-%H%M%S}-{digest}-{index:02}.jpg"
        path = directory / name
        image.save(path, "JPEG", quality=94, optimize=True)
        paths.append(path)
    caption = ig.build_caption(rates, moment) + "\n\nورق بزنید: نرخ مشتری لیر"
    if included:
        caption += "، " + "، ".join(included)
    caption += "\nنرخ بازار و صرافی‌های دیگر صرفاً جهت اطلاع‌رسانی است و با نرخ مشتری کیانی تفاوت دارد.\nلطفاً قبل از واریز هماهنگ کنید."
    if sample:
        caption = "نمونه برای بررسی طرح؛ این نرخ‌ها لحظه‌ای نیستند و قابل انتشار نیستند.\n\n" + caption
    # Save a local manifest for review without including tokens or API credentials.
    manifest = {"sample": sample, "generated_at": moment.isoformat(), "slides": [str(path) for path in paths], "sections": sections, "customer_rates": rates, "caption": caption}
    (directory / (paths[0].stem.rsplit("-", 1)[0] + ".json")).write_text(json.dumps(manifest, default=str, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return paths, caption

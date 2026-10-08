#!/usr/bin/env python3
"""Render and publish the Kiani Exchange daily Instagram rate card.

The script reads the production mini-app's raw market rates and the same
percentage adjustments used by the Telegram bot. It writes a public image for
Meta's media container API, then publishes it as a Story or feed post.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont


ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
DEFAULT_RATES_URL = "http://127.0.0.1:8000/api/rates/current"
DEFAULT_PRICING_DB_PATH = "/home/kianirad2020/send_changes/pricing_settings.db"
DEFAULT_IMAGE_DIR = "/var/lib/kiani-instagram-rates/public"
DEFAULT_STATE_PATH = "~/.local/state/kiani-instagram-rates/state.json"
GRAPH_DEFAULT_BASE_URL = "https://graph.facebook.com"

PRICING_DEFAULTS: dict[str, Decimal] = {
    "user_tl_buy_adjustment_pct": Decimal("0.67"),
    "user_tl_sell_adjustment_pct": Decimal("-3.00"),
    "user_usdt_buy_adjustment_pct": Decimal("1.00"),
    "user_usdt_sell_adjustment_pct": Decimal("-1.00"),
    "user_try_to_usdt_adjustment_pct": Decimal("2.00"),
    "user_usdt_to_try_adjustment_pct": Decimal("-2.00"),
}
MIN_ADJUSTMENT_PCT = Decimal("-50")
MAX_ADJUSTMENT_PCT = Decimal("50")
PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


class PublishError(RuntimeError):
    """Raised when required live data or Instagram publishing fails."""


def _positive_decimal(value: Any, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PublishError(f"{label} is not numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise PublishError(f"{label} must be a positive finite number")
    return parsed


def fetch_market_rates(url: str | None = None, attempts: int = 4) -> tuple[Decimal, Decimal]:
    """Fetch the raw USDT/IRR and USDT/TRY rates from the running API."""
    endpoint = (url or os.getenv("KIANI_RATES_URL", DEFAULT_RATES_URL)).strip()
    last_error: Exception | None = None

    for attempt in range(1, max(1, attempts) + 1):
        request = Request(
            endpoint,
            headers={
                "Accept": "application/json",
                "User-Agent": "KianiExchange-InstagramPublisher/1.0",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.load(response)
            raw_rates = payload.get("rates") if isinstance(payload, dict) else None
            if not isinstance(raw_rates, dict):
                raise PublishError("Rates API response does not contain a rates object")
            if "USDT_IRR" not in raw_rates or "USDT_TRY" not in raw_rates:
                raise PublishError(
                    "Rates API must return rates.USDT_IRR and rates.USDT_TRY"
                )
            return (
                _positive_decimal(raw_rates["USDT_IRR"], "USDT_IRR"),
                _positive_decimal(raw_rates["USDT_TRY"], "USDT_TRY"),
            )
        except HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            last_error = PublishError(f"Rates API returned HTTP {exc.code}: {detail}")
            retryable = exc.code in TRANSIENT_HTTP_CODES
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = PublishError(f"Could not load current rates: {exc}")
            retryable = True
        except PublishError:
            raise

        if not retryable or attempt >= max(1, attempts):
            assert last_error is not None
            raise last_error
        time.sleep(min(5 * attempt, 15))

    assert last_error is not None
    raise last_error


def _pricing_db_uri(path: Path) -> str:
    return f"file:{quote(path.resolve().as_posix(), safe='/:')}?mode=ro"


def load_pricing_factors(db_path: str | None = None) -> dict[str, Decimal]:
    """Read live bot percentages without modifying its SQLite database."""
    resolved = Path(db_path or os.getenv("PRICING_DB_PATH", DEFAULT_PRICING_DB_PATH))
    if not resolved.is_file():
        raise PublishError(f"Pricing database was not found at {resolved}")

    try:
        connection = sqlite3.connect(_pricing_db_uri(resolved), uri=True, timeout=3)
        try:
            connection.execute("PRAGMA busy_timeout = 3000")
            placeholders = ",".join("?" for _ in PRICING_DEFAULTS)
            rows = connection.execute(
                f"SELECT key, value FROM pricing_settings WHERE key IN ({placeholders})",
                tuple(PRICING_DEFAULTS),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise PublishError(f"Could not read pricing settings database: {exc}") from exc

    percentages = dict(PRICING_DEFAULTS)
    for key, raw_value in rows:
        try:
            parsed = Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if parsed.is_finite() and MIN_ADJUSTMENT_PCT <= parsed <= MAX_ADJUSTMENT_PCT:
            percentages[key] = parsed

    return {
        key: Decimal("1") + (percentage / Decimal("100"))
        for key, percentage in percentages.items()
    }


def derive_bot_rates(
    usdt_irr: Decimal,
    usdt_try: Decimal,
    factors: dict[str, Decimal],
) -> dict[str, Decimal]:
    # The Telegram bot calculates with Python floats, so preserve its exact
    # rounding behavior before converting results back to Decimal for display.
    irr = float(usdt_irr)
    try_rate = float(usdt_try)
    float_factors = {key: float(value) for key, value in factors.items()}

    def round_10(value: float) -> Decimal:
        return Decimal(int(round(value / 10.0) * 10))

    return {
        "buy_lira": round_10(((irr / 10.0) / try_rate) * float_factors["user_tl_buy_adjustment_pct"]),
        "sell_lira": round_10(((irr / 10.0) / try_rate) * float_factors["user_tl_sell_adjustment_pct"]),
        "buy_usdt": round_10((irr / 10.0) * float_factors["user_usdt_buy_adjustment_pct"]),
        "sell_usdt": round_10((irr / 10.0) * float_factors["user_usdt_sell_adjustment_pct"]),
        "lira_to_usdt": Decimal(f"{try_rate * float_factors['user_try_to_usdt_adjustment_pct']:.2f}"),
        "usdt_to_lira": Decimal(f"{try_rate * float_factors['user_usdt_to_try_adjustment_pct']:.2f}"),
    }


def _persian_number(value: Decimal, decimals: int = 0) -> str:
    if decimals:
        rendered = f"{value.quantize(Decimal('1').scaleb(-decimals), rounding=ROUND_HALF_EVEN):.{decimals}f}"
        rendered = rendered.rstrip("0").rstrip(".")
        rendered = rendered.replace(".", "٫")
    else:
        rendered = f"{int(value):,}".replace(",", "٬")
    return rendered.translate(PERSIAN_DIGITS)


def build_caption(rates: dict[str, Decimal], moment: datetime) -> str:
    local_time = moment.astimezone(ISTANBUL_TZ).strftime("%H:%M").translate(PERSIAN_DIGITS)
    return "\n".join(
        [
            "صرافی کیانی | نرخ امروز",
            "",
            "🇹🇷 لیر",
            f"🟢 از ما می‌خرید: {_persian_number(rates['buy_lira'])} تومان",
            f"🔵 به ما می‌فروشید: {_persian_number(rates['sell_lira'])} تومان",
            "",
            "💵 تتر",
            f"🟢 از ما می‌خرید: {_persian_number(rates['buy_usdt'])} تومان",
            f"🔵 به ما می‌فروشید: {_persian_number(rates['sell_usdt'])} تومان",
            "",
            f"🔁 لیر ← تتر: {_persian_number(rates['lira_to_usdt'], 2)} لیر",
            f"🔁 تتر ← لیر: {_persian_number(rates['usdt_to_lira'], 2)} لیر",
            "",
            f"🕰 {local_time} استانبول",
            "👇 سفارش: لینک در Bio",
        ]
    )


def _font_path() -> str:
    configured = os.getenv("VAZIRMATN_FONT_PATH", "").strip()
    try:
        discovered = subprocess.run(
            ["fc-match", "-f", "%{file}", "Vazirmatn"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        discovered = ""
    bundled = Path(__file__).resolve().parent / "fonts" / "Vazirmatn-Regular.ttf"
    candidates = [
        configured,
        str(bundled),
        discovered if "vazirmatn" in discovered.lower() else "",
        "/usr/share/fonts/truetype/vazirmatn/Vazirmatn[wght].ttf",
        "/usr/share/fonts/truetype/vazirmatn/Vazirmatn-FD[wght].ttf",
        "/usr/share/fonts/opentype/vazirmatn/Vazirmatn[wght].ttf",
        "/usr/share/fonts/truetype/vazir/Vazirmatn.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise PublishError(
        "Vazirmatn font was not found. Restore fonts/Vazirmatn-Regular.ttf or set VAZIRMATN_FONT_PATH."
    )


def _rtl(text: str) -> str:
    return get_display(arabic_reshaper.reshape(text), base_dir="R")


def _draw_rtl(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: str,
    anchor: str = "mm",
) -> None:
    draw.text(xy, _rtl(text), font=font, fill=fill, anchor=anchor)


def _load_fonts(path: str, mode: str) -> dict[str, ImageFont.FreeTypeFont]:
    sizes = (
        {
            "brand": 68,
            "subhead": 36,
            "card_head": 42,
            "label": 50,
            "value": 62,
            "unit": 28,
            "cross_label": 36,
            "cross_value": 42,
            "footer": 34,
            "cta": 42,
        }
        if mode == "story"
        else {
            "brand": 60,
            "subhead": 34,
            "card_head": 38,
            "label": 40,
            "value": 52,
            "unit": 24,
            "cross_label": 32,
            "cross_value": 38,
            "footer": 30,
            "cta": 36,
        }
    )
    return {name: ImageFont.truetype(path, size) for name, size in sizes.items()}


def _draw_shadow_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = box
    draw.rounded_rectangle(
        (left + 4, top + 10, right + 4, bottom + 10),
        radius=34,
        fill="#E5ECE8",
    )
    draw.rounded_rectangle(box, radius=34, fill="#FFFFFF", outline="#E1E9E4", width=2)


def _draw_turkish_mark(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: int) -> None:
    width, height = 70 * scale, 46 * scale
    left, top = cx - width // 2, cy - height // 2
    draw.rounded_rectangle((left, top, left + width, top + height), radius=8 * scale, fill="#D84545")
    radius = 13 * scale
    draw.ellipse((left + 23 * scale, top + 10 * scale, left + 23 * scale + radius * 2, top + 10 * scale + radius * 2), fill="#FFFFFF")
    draw.ellipse((left + 29 * scale, top + 8 * scale, left + 29 * scale + radius * 2, top + 8 * scale + radius * 2), fill="#D84545")
    draw.regular_polygon((left + 53 * scale, top + 23 * scale, 8 * scale), n_sides=5, rotation=-90, fill="#FFFFFF")


def _draw_tether_mark(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: int) -> None:
    radius = 25 * scale
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill="#2D9272")
    line_width = max(2, 4 * scale)
    draw.rounded_rectangle((cx - 15 * scale, cy - 12 * scale, cx + 15 * scale, cy - 5 * scale), radius=3 * scale, fill="#FFFFFF")
    draw.rounded_rectangle((cx - 4 * scale, cy - 6 * scale, cx + 4 * scale, cy + 16 * scale), radius=3 * scale, fill="#FFFFFF")
    draw.line((cx - 12 * scale, cy + 1 * scale, cx + 12 * scale, cy + 1 * scale), fill="#FFFFFF", width=line_width)


def _draw_rate_card(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.FreeTypeFont],
    box: tuple[int, int, int, int],
    title: str,
    icon: str,
    rows: list[tuple[str, Decimal, str]],
    mode: str,
) -> None:
    left, top, right, _bottom = box
    _draw_shadow_card(draw, box)
    scale = 1
    icon_center = (left + 90, top + (70 if mode == "story" else 60))
    if icon == "turkey":
        _draw_turkish_mark(draw, *icon_center, scale)
    else:
        _draw_tether_mark(draw, *icon_center, scale)
    _draw_rtl(draw, title, (left + 190, icon_center[1]), fonts["card_head"], "#183B35", anchor="lm")

    row_height = 142 if mode == "story" else 90
    first_row_top = top + (145 if mode == "story" else 100)
    for index, (label, value, dot_color) in enumerate(rows):
        row_y = first_row_top + index * row_height
        draw.ellipse((right - 105, row_y + 17, right - 81, row_y + 41), fill=dot_color)
        _draw_rtl(draw, label, (right - 128, row_y + 29), fonts["label"], "#183B35", anchor="rm")
        draw.text(
            (left + 78, row_y + 23),
            _persian_number(value),
            font=fonts["value"],
            fill="#102F2A",
            anchor="lm",
        )
        _draw_rtl(
            draw,
            "تومان",
            (left + 83, row_y + (70 if mode == "story" else 59)),
            fonts["unit"],
            "#72857E",
            anchor="lm",
        )


def _draw_clock(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int) -> None:
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline="#729087", width=3)
    draw.line((cx, cy, cx, cy - radius // 2), fill="#729087", width=3)
    draw.line((cx, cy, cx + radius // 2, cy + radius // 4), fill="#729087", width=3)


def render_banner(rates: dict[str, Decimal], moment: datetime, mode: str, output_path: Path) -> None:
    if mode not in {"story", "feed"}:
        raise PublishError("INSTAGRAM_PUBLISH_MODE must be 'story' or 'feed'")

    width, height = (1080, 1920) if mode == "story" else (1080, 1350)
    font = _font_path()
    fonts = _load_fonts(font, mode)
    image = Image.new("RGB", (width, height), "#F4F8F5")
    draw = ImageDraw.Draw(image)

    # A quiet decorative stripe keeps the light layout on brand without making
    # any of the Persian copy compete with the rates.
    draw.rounded_rectangle((58, 58, width - 58, 75), radius=8, fill="#DDEBE4")
    draw.rounded_rectangle((58, 58, 250, 75), radius=8, fill="#2D9272")
    mark_y = 172 if mode == "story" else 134
    draw.ellipse((width // 2 - 42, mark_y - 42, width // 2 + 42, mark_y + 42), fill="#E1F0E8")
    _draw_rtl(draw, "K", (width // 2, mark_y), ImageFont.truetype(font, 42), "#287A60")

    brand_y = 255 if mode == "story" else 220
    subtitle_y = 325 if mode == "story" else 275
    _draw_rtl(draw, "صرافی کیانی", (width // 2, brand_y), fonts["brand"], "#133B32")
    _draw_rtl(draw, "نرخ امروز", (width // 2, subtitle_y), fonts["subhead"], "#71847C")

    if mode == "story":
        first_box = (70, 400, width - 70, 835)
        second_box = (70, 875, width - 70, 1310)
        cross_box = (70, 1350, width - 70, 1625)
        time_y, cta_y = 1710, 1820
    else:
        first_box = (70, 315, width - 70, 605)
        second_box = (70, 625, width - 70, 915)
        cross_box = (70, 935, width - 70, 1135)
        time_y, cta_y = 1175, 1275

    _draw_rate_card(
        draw,
        fonts,
        first_box,
        "لیر",
        "turkey",
        [("از ما می‌خرید", rates["buy_lira"], "#27956E"), ("به ما می‌فروشید", rates["sell_lira"], "#3985B8")],
        mode,
    )
    _draw_rate_card(
        draw,
        fonts,
        second_box,
        "تتر",
        "tether",
        [("از ما می‌خرید", rates["buy_usdt"], "#27956E"), ("به ما می‌فروشید", rates["sell_usdt"], "#3985B8")],
        mode,
    )

    left, top, right, bottom = cross_box
    _draw_shadow_card(draw, cross_box)
    _draw_rtl(draw, "نرخ تبدیل", (width // 2, top + (48 if mode == "story" else 38)), fonts["cross_label"], "#71847C")
    cross_rows = [
        ("لیر ← تتر", rates["lira_to_usdt"]),
        ("تتر ← لیر", rates["usdt_to_lira"]),
    ]
    cross_row_y = top + (118 if mode == "story" else 95)
    cross_spacing = 78 if mode == "story" else 56
    for index, (label, value) in enumerate(cross_rows):
        y = cross_row_y + index * cross_spacing
        _draw_rtl(draw, label, (right - 72, y), fonts["cross_label"], "#183B35", anchor="rm")
        draw.text(
            (left + 72, y),
            _rtl(_persian_number(value, 2) + " لیر"),
            font=fonts["cross_value"],
            fill="#102F2A",
            anchor="lm",
        )

    local_time = moment.astimezone(ISTANBUL_TZ).strftime("%H:%M").translate(PERSIAN_DIGITS)
    _draw_clock(draw, width // 2 - 118, time_y, 19)
    draw.text((width // 2 - 75, time_y), local_time, font=fonts["footer"], fill="#526A61", anchor="lm")
    _draw_rtl(draw, "استانبول", (width // 2 + 40, time_y), fonts["footer"], "#526A61", anchor="lm")
    draw.line((width // 2 - 92, cta_y - 54, width // 2 - 92, cta_y - 25), fill="#2D9272", width=4)
    draw.polygon(
        [(width // 2 - 103, cta_y - 35), (width // 2 - 92, cta_y - 23), (width // 2 - 81, cta_y - 35)],
        fill="#2D9272",
    )
    _draw_rtl(draw, "سفارش: لینک در Bio", (width // 2, cta_y), fonts["cta"], "#1D7659")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=94, optimize=True, progressive=True)


def _public_image_url(path: Path) -> str:
    base = os.getenv("INSTAGRAM_PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
    if not base.startswith("https://"):
        raise PublishError("Set INSTAGRAM_PUBLIC_MEDIA_BASE_URL to the HTTPS URL serving the banner directory")
    return f"{base}/{quote(path.name)}"


def _graph_base() -> str:
    base = os.getenv("INSTAGRAM_GRAPH_BASE_URL", GRAPH_DEFAULT_BASE_URL).strip().rstrip("/")
    version = os.getenv("INSTAGRAM_GRAPH_API_VERSION", "").strip().strip("/")
    if not version or not re.fullmatch(r"v\d+\.\d+", version):
        raise PublishError("Set INSTAGRAM_GRAPH_API_VERSION to the version enabled for your Meta app")
    return f"{base}/{version}"


def _graph_request(
    path: str,
    method: str,
    fields: dict[str, str],
    object_id: str | None = None,
) -> dict[str, Any]:
    user_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not user_id or not token:
        raise PublishError("Set INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN in the server environment")
    url = f"{_graph_base()}/{object_id or user_id}{path}"
    if method.upper() != "POST" and fields:
        url = f"{url}?{urlencode(fields)}"
    try:
        # Keep tokens out of URLs and shell logs.
        data = urlencode(fields).encode("utf-8") if method.upper() == "POST" else None
        request = Request(
            url,
            data=data,
            method=method.upper(),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "KianiExchange-InstagramPublisher/1.0",
                **({"Content-Type": "application/x-www-form-urlencoded"} if data is not None else {}),
            },
        )
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise PublishError(f"Instagram API returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise PublishError(f"Could not reach Instagram API: {exc}") from exc
    if not isinstance(payload, dict):
        raise PublishError("Instagram API returned an unexpected response")
    if isinstance(payload.get("error"), dict):
        message = payload["error"].get("message", "Unknown Graph API error")
        raise PublishError(f"Instagram API error: {message}")
    return payload


def verify_public_image(url: str) -> None:
    request = Request(url, method="GET", headers={"User-Agent": "KianiExchange-InstagramPublisher/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            content_type = response.headers.get_content_type()
            first_bytes = response.read(8)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise PublishError(f"Meta cannot fetch the public banner URL: {exc}") from exc
    if content_type != "image/jpeg" or not first_bytes.startswith(b"\xff\xd8\xff"):
        raise PublishError("Public banner URL did not return a JPEG image")


def publish_image(image_url: str, mode: str, caption: str) -> str:
    fields = {"image_url": image_url}
    if mode == "story":
        fields["media_type"] = "STORIES"
    else:
        fields["caption"] = caption
    container = _graph_request("/media", "POST", fields)
    container_id = str(container.get("id", "")).strip()
    if not container_id:
        raise PublishError("Instagram did not return a media container ID")

    for _ in range(30):
        status = _graph_request(
            "",
            "GET",
            {"fields": "status_code,status"},
            object_id=container_id,
        )
        status_code = str(status.get("status_code", "")).upper()
        if status_code in {"FINISHED", "PUBLISHED"} or not status_code:
            break
        if status_code == "ERROR":
            raise PublishError(f"Instagram media processing failed: {status.get('status', 'unknown error')}")
        time.sleep(2)
    else:
        raise PublishError("Instagram media container did not finish processing in time")

    published = _graph_request(
        "/media_publish",
        "POST",
        {"creation_id": container_id},
    )
    media_id = str(published.get("id", "")).strip()
    if not media_id:
        raise PublishError("Instagram did not return the published media ID")
    return media_id


def _load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"Could not read Instagram publish state at {path}: {exc}") from exc
    return payload if isinstance(payload, dict) else None


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix="instagram-rates-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(state, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and publish the daily Kiani Exchange Instagram rate card")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="Render and preview without publishing (default)")
    action.add_argument("--publish", action="store_true", help="Publish the rendered image to Instagram")
    parser.add_argument("--force", action="store_true", help="Allow a second post on the same Istanbul calendar day")
    parser.add_argument("--output", type=Path, default=None, help="Override the public image output directory")
    args = parser.parse_args()
    if args.force and not args.publish:
        parser.error("--force requires --publish")

    mode = os.getenv("INSTAGRAM_PUBLISH_MODE", "story").strip().lower()
    if mode not in {"story", "feed"}:
        raise PublishError("INSTAGRAM_PUBLISH_MODE must be 'story' or 'feed'")

    now = datetime.now(ISTANBUL_TZ)
    state_path = Path(os.path.expanduser(os.getenv("INSTAGRAM_STATE_FILE", DEFAULT_STATE_PATH)))
    state = _load_state(state_path)
    today = now.date().isoformat()
    if args.publish and not args.force and state and state.get("posted_date") == today:
        print(f"Instagram banner already published for {today}; skipping duplicate run.")
        return 0

    raw_irr, raw_try = fetch_market_rates()
    factors = load_pricing_factors()
    rates = derive_bot_rates(raw_irr, raw_try, factors)

    image_dir = args.output or Path(os.getenv("INSTAGRAM_IMAGE_OUTPUT_DIR", DEFAULT_IMAGE_DIR))
    image_dir = image_dir.expanduser().resolve()
    width = 1080
    image_height = 1920 if mode == "story" else 1350
    rate_digest = hashlib.sha256(
        json.dumps({key: str(value) for key, value in rates.items()}, sort_keys=True).encode("utf-8")
    ).hexdigest()[:10]
    image_path = image_dir / f"kiani-rates-{today}-{rate_digest}-{now:%H%M%S}.jpg"
    render_banner(rates, now, mode, image_path)
    try:
        image_url = _public_image_url(image_path)
    except PublishError:
        if args.publish:
            raise
        image_url = ""

    print(f"Rendered {width}x{image_height} {mode} banner: {image_path}")
    if image_url:
        print(f"Public media URL: {image_url}")
    elif not args.publish:
        print("Public media URL is not configured; the local preview was still rendered.")
    if not args.publish:
        if mode == "feed":
            print(build_caption(rates, now))
        print("Dry run complete; Instagram was not contacted.")
        return 0

    verify_public_image(image_url)
    media_id = publish_image(image_url, mode, build_caption(rates, now))
    _save_state(
        state_path,
        {
            "posted_date": today,
            "posted_at": now.isoformat(),
            "mode": mode,
            "media_id": media_id,
            "image_url": image_url,
        },
    )
    print(f"Published Kiani Exchange Instagram {mode} (media id: {media_id})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublishError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


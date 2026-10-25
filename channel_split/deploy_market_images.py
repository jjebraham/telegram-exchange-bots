#!/usr/bin/env python3
"""Guarded, idempotent deployment patch for five AlanChande market image posts.

Does not activate image mode, restart services, publish messages or touch DBs.
Only the server checkout's publisher integration, renderer, and bundled artwork
are changed. An upgrade leaves the installed publisher file byte-for-byte intact.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
from pathlib import Path
import shutil
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--repo", default="/home/kianirad2020/telegram_bot_repo")
parser.add_argument("--apply", action="store_true")
parser.add_argument("--upgrade-renderer", action="store_true",
                    help="Update artwork/renderer only when the installed publisher integration matches exactly")
parser.add_argument("--backup-dir", type=Path, default=Path.home() / "kiani-image-backups")
args = parser.parse_args()

repo = Path(args.repo).expanduser().resolve()
main = repo / "channel_split/publish_channels.py"
renderer = repo / "channel_split/market_images.py"
source = Path(__file__).resolve().with_name("market_images.py")
source_assets = source.with_name("market_image_assets")
target_assets = renderer.with_name("market_image_assets")

if not main.is_file() or not source.is_file():
    sys.exit("STOP: missing production publisher or image module")
asset_names = ("vazirmatn.ttf", "vazirmatn-OFL.txt", "SOURCES.md", "tether-art.png",
               "nobitex.png", "wallex.png", "tabdeal.png", "ramzinex.png", "raastin.png", "exir.png", "bitpin.png")
if not all((source_assets / name).is_file() for name in asset_names):
    sys.exit("STOP: bundled renderer artwork or OFL font license is missing")
original = main.read_text(encoding="utf-8")

anchors = [
    (
        'DEFAULT_RATES_URL = "https://miniapp.kiani.exchange/api/rates/current"',
        'from market_images import SUPPORTED_MARKETS, render_png, telegram_send_photo\n\n'
        'DEFAULT_RATES_URL = "https://miniapp.kiani.exchange/api/rates/current"',
    ),
    (
        '            send_result = telegram_send(token, chat_id, text)',
        '''            if (
                destination_env == "ALANCHANDE_CHANNEL_ID"
                and post_key in SUPPORTED_MARKETS
                and os.environ.get("ALANCHANDE_POST_FORMAT", "text").lower() == "image"
            ):
                import tempfile
                with tempfile.TemporaryDirectory(prefix="alanchande-market-image-") as temp:
                    image_path = Path(temp) / f"{post_key}.png"
                    render_png(post_key, text, image_path)
                    captions = {
                        "usdt": "💎 قیمت تتر در صرافی‌های ایران",
                        "iran-fx": "💱 نرخ ارز آزاد ایران",
                        "iran-gold": "🪙 طلا و سکه ایران",
                        "turkey-gold": "🥇 قیمت طلای ترکیه",
                        "fx-pulse": "📊 نبض بازار ارز ترکیه",
                    }
                    send_result = telegram_send_photo(
                        token, chat_id, image_path,
                        captions[post_key] + "\\n@alanchande_com",
                    )
            else:
                send_result = telegram_send(token, chat_id, text)''',
    ),
    (
        '        for token_env, destination_env, text, post_key, safety in jobs:\n            if safety is not None:',
        '''        for token_env, destination_env, text, post_key, safety in jobs:
            preview_dir = os.environ.get("ALANCHANDE_IMAGE_PREVIEW_DIR", "").strip()
            if (
                preview_dir
                and destination_env == "ALANCHANDE_CHANNEL_ID"
                and post_key in SUPPORTED_MARKETS
                and (safety is None or publication_allowed(safety_mode, safety))
            ):
                preview = Path(preview_dir).expanduser() / f"{post_key}.png"
                render_png(post_key, text, preview)
                print(f"IMAGE PREVIEW -> {preview} (NOT SENT)")
            if safety is not None:''',
    ),
]

if "from market_images import SUPPORTED_MARKETS" in original:
    # Never re-patch or replace a publisher whose integration was modified.
    if any(original.count(new) != 1 for old, new in anchors):
        sys.exit("STOP: installed image-publisher integration differs; review changes manually")
    exact_assets = all((target_assets / name).is_file()
                       and (target_assets / name).read_bytes() == (source_assets / name).read_bytes()
                       for name in asset_names)
    if renderer.is_file() and renderer.read_bytes() == source.read_bytes() and exact_assets:
        print("PASS: exact image publisher and assets already installed; no changes necessary")
        raise SystemExit(0)
    if not args.upgrade_renderer:
        sys.exit("STOP: another renderer version installed; use --upgrade-renderer after review")
    patched = original
else:
    patched = original
    for old, new in anchors:
        matches = patched.count(old)
        if matches != 1:
            sys.exit(f"STOP: expected one matching publisher anchor, found {matches}: {old[:90]!r}")
        patched = patched.replace(old, new, 1)
ast.parse(patched)
ast.parse(source.read_text(encoding="utf-8"))

if not args.apply:
    print("PASS: publisher patch anchors and Python AST validated (dry run)")
    raise SystemExit(0)

backup = args.backup_dir.expanduser().resolve() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(main, backup / main.name)
if renderer.exists():
    shutil.copy2(renderer, backup / renderer.name)
existing_assets = {name for name in asset_names if (target_assets / name).is_file()}
if existing_assets:
    (backup / "market_image_assets").mkdir()
    for name in existing_assets:
        shutil.copy2(target_assets / name, backup / "market_image_assets" / name)

try:
    target_assets.mkdir(exist_ok=True)
    for name in asset_names:
        shutil.copy2(source_assets / name, target_assets / name)
    shutil.copy2(source, renderer)
    if patched != original:
        main.write_text(patched, encoding="utf-8")
    ast.parse(main.read_text(encoding="utf-8"))
except Exception:
    shutil.copy2(backup/main.name, main)
    if (backup/renderer.name).exists():
        shutil.copy2(backup/renderer.name, renderer)
    elif renderer.exists():
        renderer.unlink()
    for name in asset_names:
        if name in existing_assets:
            shutil.copy2(backup / "market_image_assets" / name, target_assets / name)
        elif (target_assets / name).is_file():
            (target_assets / name).unlink()
    raise

print("PATCHED:", main)
print("COPIED:", renderer)
print("ASSETS:", target_assets)
print("BACKUP:", backup)
print("SAFE DEFAULT: ALANCHANDE_POST_FORMAT=text (unless already changed on server)")

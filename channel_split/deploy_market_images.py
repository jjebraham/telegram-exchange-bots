#!/usr/bin/env python3
"""Guarded, idempotent deployment patch for five AlanChande market image posts.

Does not activate image mode, restart services, publish messages or touch DBs.
Only the server checkout's publish_channels.py and market_images.py are changed.
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
args = parser.parse_args()

repo = Path(args.repo).expanduser().resolve()
main = repo / "channel_split/publish_channels.py"
renderer = repo / "channel_split/market_images.py"
source = Path(__file__).resolve().with_name("market_images.py")

if not main.is_file() or not source.is_file():
    sys.exit("STOP: missing production publisher or image module")
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
    sys.exit("STOP: image publisher patch already installed; inspect before rerunning")
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

backup = Path.home() / "kiani-image-backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(main, backup / main.name)
if renderer.exists():
    shutil.copy2(renderer, backup / renderer.name)

try:
    shutil.copy2(source, renderer)
    main.write_text(patched, encoding="utf-8")
    ast.parse(main.read_text(encoding="utf-8"))
except Exception:
    shutil.copy2(backup/main.name, main)
    if (backup/renderer.name).exists():
        shutil.copy2(backup/renderer.name, renderer)
    elif renderer.exists():
        renderer.unlink()
    raise

print("PATCHED:", main)
print("COPIED:", renderer)
print("BACKUP:", backup)
print("SAFE DEFAULT: ALANCHANDE_POST_FORMAT=text (unless already changed on server)")

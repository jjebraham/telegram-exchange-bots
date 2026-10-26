#!/usr/bin/env python3
"""Guarded, idempotent deployment patch for five AlanChande market image posts.

Does not activate image mode, restart services, publish messages or touch DBs.
Only the server checkout's publisher integration, renderer, and bundled artwork
are changed. Renderer-only upgrades preserve the installed publisher bytes;
the known photo-only integration needs an explicit --upgrade-integration.
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
parser.add_argument("--upgrade-integration", action="store_true",
                    help="Migrate a known earlier integration to selectable full or links-only captions")
parser.add_argument("--backup-dir", type=Path, default=Path.home() / "kiani-image-backups")
args = parser.parse_args()

repo = Path(args.repo).expanduser().resolve()
main = repo / "channel_split/publish_channels.py"
renderer = repo / "channel_split/market_images.py"
source = Path(__file__).resolve().with_name("market_images.py")
source_assets = source.with_name("market_image_assets")
target_assets = renderer.with_name("market_image_assets")
report_source = source.with_name("market_report_templates.py")
report_target = renderer.with_name("market_report_templates.py")

if not main.is_file() or not source.is_file() or not report_source.is_file():
    sys.exit("STOP: missing production publisher or image module")
asset_names = ("vazirmatn.ttf", "vazirmatn-OFL.txt", "SOURCES.md", "tether-art.png",
               "nobitex.png", "wallex.png", "tabdeal.png", "ramzinex.png", "raastin.png", "exir.png", "bitpin.png")
asset_names += ("flags/LICENSE.txt", "flags/sources.json") + tuple(
    f"flags/{country}.svg" for country in
    'us eu gb ch ca au se no ru th sg hk az dk ae tr cn sa in my af kw bh om qa'.split())
if not all((source_assets / name).is_file() for name in asset_names):
    sys.exit("STOP: bundled renderer artwork or OFL font license is missing")
original = main.read_text(encoding="utf-8")

anchors = [
    (
        'DEFAULT_RATES_URL = "https://miniapp.kiani.exchange/api/rates/current"',
        'from market_images import SUPPORTED_MARKETS, render_png, telegram_send_photo, image_post_details\n\n'
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
                        details_text=image_post_details(post_key, text),
                        details_as_caption=post_key != "iran-fx",
                        caption_style=os.environ.get("ALANCHANDE_IMAGE_CAPTION_STYLE", "full"),
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

legacy_import = anchors[0][1].replace(', image_post_details', '')
caption_style_line = '                        caption_style=os.environ.get("ALANCHANDE_IMAGE_CAPTION_STYLE", "full"),\n'
legacy_full_send = anchors[1][1].replace(caption_style_line, '')
legacy_fx_send = legacy_full_send.replace('details_text=image_post_details(post_key, text)',
                                    'details_text=text if post_key == "iran-fx" else None')
caption_option_line = '                        details_as_caption=post_key != "iran-fx",\n'
legacy_fx_send = legacy_fx_send.replace(caption_option_line, '')
legacy_photo_send = legacy_full_send.replace('                        details_text=image_post_details(post_key, text),\n', '').replace(
    caption_option_line, '')
legacy_usdt_send = legacy_full_send.replace('details_as_caption=post_key != "iran-fx"',
                                      'details_as_caption=post_key == "usdt"')
legacy_pulse_send = legacy_full_send.replace('details_as_caption=post_key != "iran-fx"',
                                       'details_as_caption=post_key in {"usdt", "fx-pulse"}')
legacy_integrations = ((anchors[0][1],legacy_full_send),(legacy_import,legacy_fx_send),(legacy_import,legacy_photo_send),
                       (anchors[0][1],legacy_usdt_send),(anchors[0][1],legacy_pulse_send))

if "from market_images import SUPPORTED_MARKETS" in original:
    # Never re-patch or replace a publisher whose integration was modified.
    patched = original
    legacy = next(((import_line,send_block) for import_line,send_block in legacy_integrations
                   if original.count(import_line)==1 and original.count(send_block)==1
                   and original.count(anchors[2][1])==1),None)
    if all(original.count(new) == 1 for old, new in anchors):
        pass
    elif legacy is not None:
        if not args.upgrade_integration:
            sys.exit("STOP: earlier image integration installed; review and use --upgrade-integration for caption styles")
        legacy_import_line,legacy_send = legacy
        patched = original.replace(legacy_import_line, anchors[0][1], 1).replace(legacy_send, anchors[1][1], 1)
    else:
        sys.exit("STOP: installed image-publisher integration differs; review changes manually")
    exact_assets = all((target_assets / name).is_file()
                       and (target_assets / name).read_bytes() == (source_assets / name).read_bytes()
                       for name in asset_names)
    exact_module = report_target.is_file() and report_target.read_bytes() == report_source.read_bytes()
    if patched == original and renderer.is_file() and renderer.read_bytes() == source.read_bytes() and exact_assets and exact_module:
        print("PASS: exact image publisher and assets already installed; no changes necessary")
        raise SystemExit(0)
    if not (args.upgrade_renderer or args.upgrade_integration):
        sys.exit("STOP: another renderer version installed; use --upgrade-renderer after review")
else:
    patched = original
    for old, new in anchors:
        matches = patched.count(old)
        if matches != 1:
            sys.exit(f"STOP: expected one matching publisher anchor, found {matches}: {old[:90]!r}")
        patched = patched.replace(old, new, 1)
ast.parse(patched)
ast.parse(source.read_text(encoding="utf-8"))
ast.parse(report_source.read_text(encoding="utf-8"))

if not args.apply:
    print("PASS: publisher patch anchors and Python AST validated (dry run)")
    raise SystemExit(0)

backup = args.backup_dir.expanduser().resolve() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(main, backup / main.name)
if renderer.exists():
    shutil.copy2(renderer, backup / renderer.name)
had_report = report_target.is_file()
if had_report:
    shutil.copy2(report_target, backup / report_target.name)
existing_assets = {name for name in asset_names if (target_assets / name).is_file()}
if existing_assets:
    (backup / "market_image_assets").mkdir()
    for name in existing_assets:
        (backup / "market_image_assets" / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_assets / name, backup / "market_image_assets" / name)

try:
    target_assets.mkdir(exist_ok=True)
    for name in asset_names:
        (target_assets / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_assets / name, target_assets / name)
    shutil.copy2(report_source, report_target)
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
    if had_report:
        shutil.copy2(backup / report_target.name, report_target)
    elif report_target.exists():
        report_target.unlink()
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

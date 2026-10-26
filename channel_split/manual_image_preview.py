#!/usr/bin/env python3
"""Manually publish ONE approved AlanChande image to @alanchandetest.

Does not install, edit, restart, or alter production scheduling. Uses the
existing production publisher in read-only --dry-run mode, checks VERIFIED
market-safety assessment and uploads exactly one live-data image.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from market_images import TITLES, IncompleteImagePostError, image_post_details, render_png, telegram_send_photo

POSTS = {
    "usdt": "alanchande-usdt-exchanges",
    "iran-fx": "alanchande-iran-fx",
    "iran-gold": "alanchande-iran-gold",
    "turkey-gold": "alanchande-turkey-gold",
    "fx-pulse": "alanchande-fx-pulse",
}
DEST = "@alanchandetest"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=tuple(POSTS), default="usdt")
    parser.add_argument("--send-test", action="store_true", help="Upload exactly ONE photo to @alanchandetest")
    parser.add_argument("--sample", action="store_true", help="Use DEMO data, visibly watermarked, no live market validation")
    parser.add_argument("--output", type=Path, help="Optional review PNG path; does not change the fixed TEST destination")
    args = parser.parse_args()

    live = Path.home() / "telegram_bot_repo/channel_split"
    publisher = live / "publish_channels.py"
    if not publisher.is_file():
        raise SystemExit("STOP: live publisher was not found")
    if args.sample:
        from test_market_images import SAMPLES, SAMPLE_TIMES
        approved_text = SAMPLES[args.kind]
        print("DESIGN DEMO: the prices below are illustrative, not live market data.")
    else:
        env = os.environ.copy()
        env["MARKET_SAFETY_MODE"] = "enforce"
        env["MARKET_HISTORY_DB"] = "market_history_production.sqlite3"
        env.pop("ALANCHANDE_IMAGE_PREVIEW_DIR", None)
        result = subprocess.run(
            ["/usr/bin/python3", str(publisher), "--post", POSTS[args.kind], "--dry-run"],
            cwd=live, env=env, capture_output=True, text=True, timeout=160, check=False,
        )
        if result.returncode:
            print(result.stderr[-1200:], file=sys.stderr)
            raise SystemExit("STOP: live market verification unavailable; no photo sent")
        safety = re.search(rf"(?m)^SAFETY {re.escape(args.kind)}:\s+(\S+)", result.stdout)
        if safety is None or safety.group(1) != "VERIFIED":
            decision = safety.group(1) if safety else "not found"
            raise SystemExit(f"STOP: {args.kind} safety decision {decision}; no photo sent")
        marker = "===== ALANCHANDE_CHANNEL_ID (bot: ALANCHANDE_TELEGRAM_BOT_TOKEN) =====\n"
        if result.stdout.count(marker) != 1:
            raise SystemExit("STOP: exact AlanChande publisher output missing or ambiguous")
        approved_text = result.stdout.split(marker, 1)[1].strip()
        print("Market-safety decision: VERIFIED")

    filename = f"{args.kind}-{'sample' if args.sample else 'live'}-manual.png"
    target = args.output or Path.home() / "alanchande-image-previews" / filename
    render_png(args.kind, approved_text, target, demo=args.sample,
               now=SAMPLE_TIMES[args.kind] if args.sample else None)
    print(f"Rendered: {target} ({target.stat().st_size:,} bytes)")
    details_text = image_post_details(args.kind, approved_text, demo=args.sample)
    if details_text is not None:
        # Keep every value, period, omission note and source time from the same
        # verified snapshot used to render this image. Never fetch a second time.
        details_path = target.with_suffix('.details.html')
        details_path.write_text(details_text, encoding='utf-8')
        print(f"Full text: {details_path}")

    if not args.send_test:
        print("Not sent. Add --send-test to post ONE photo to @alanchandetest.")
        return 0

    # Reuse the existing secret loader without exposing the token or changing
    # channel configuration. The public destination remains hardcoded to TEST.
    sys.path.insert(0, str(live))
    from publish_channels import _load_local_env
    _load_local_env()
    token = os.environ.get("ALANCHANDE_TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("STOP: existing AlanChande bot token unavailable; no photo sent")

    caption = (
        f"🧪 نمونه آزمایشی — {TITLES[args.kind]}\n⚠️ قیمت‌ها ساختگی هستند."
        if args.sample else
        f"✅ پیش‌نمایش نرخ‌های تأییدشده — {TITLES[args.kind]}\nفقط کانال آزمایشی."
    )
    if details_text is not None:
        caption += '\nجزئیات نرخ‌ها و تغییرات در پیام متنی همراه.'
    try:
        response = telegram_send_photo(token, DEST, target, caption, details_text=details_text,
                                       details_as_caption=args.kind!='iran-fx')
    except IncompleteImagePostError as error:
        target.with_suffix('.receipt.json').write_text(
            json.dumps({'status':'photo_sent_details_unconfirmed',
                                     'photo_message_id':error.photo_response['result']['message_id']}, indent=2)+'\n',
            encoding='utf-8')
        raise SystemExit(str(error)) from None
    message_id = int(response["result"]["message_id"])
    receipt = {'status':'sent','photo_message_id':message_id}
    if response.get('details_in_caption'):
        receipt.update(details_message_id=message_id,details_in_caption=True)
        print('Full text included in the photo caption')
    elif 'details_result' in response:
        details_id = int(response['details_result']['message_id'])
        receipt['details_message_id'] = details_id
        print(f"Full details sent: https://t.me/alanchandetest/{details_id}")
    target.with_suffix('.receipt.json').write_text(json.dumps(receipt,indent=2)+'\n', encoding='utf-8')
    print(f"SUCCESS: ONE photo posted to {DEST}; message ID={message_id}")
    print(f"https://t.me/alanchandetest/{message_id}")
    print("No changes to @alanchande_com or existing schedules")
    return 0


if __name__ == "__main__":
    sys.exit(main())

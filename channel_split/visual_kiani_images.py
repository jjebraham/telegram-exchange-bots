"""Generate four visibly illustrative Kiani proofs for visual review."""
import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from kiani_posts import (build_kiani_rate_post, build_kiani_try_post,
                         build_kiani_try_receive_post, build_kiani_toman_receive_post)
from kiani_images import kiani_html, render_kiani_png

SAMPLE_TIME = datetime(2026, 10, 26, 14, 10, tzinfo=ZoneInfo('Europe/Istanbul'))
SAMPLE_RATES = {'buy_lira': Decimal('5520'), 'sell_lira': Decimal('5350'),
                'buy_usdt': Decimal('274060'), 'sell_usdt': Decimal('268640'),
                'lira_to_usdt': Decimal('50.66'), 'usdt_to_lira': Decimal('48.68')}


def samples():
    return {'kiani-rates': build_kiani_rate_post(SAMPLE_RATES, now=SAMPLE_TIME),
            'kiani-try': build_kiani_try_post(SAMPLE_RATES, now=SAMPLE_TIME),
            'kiani-examples': build_kiani_try_receive_post(SAMPLE_RATES),
            'kiani-examples-reverse': build_kiani_toman_receive_post(SAMPLE_RATES)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--skip-sheet', action='store_true', help='Render PNGs without the optional Pillow contact sheet')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    images = []
    for kind, text in samples().items():
        (args.output_dir / (kind + '.source.html')).write_text(text, encoding='utf-8')
        (args.output_dir / (kind + '.html')).write_text(kiani_html(kind, text, now=SAMPLE_TIME, demo=True), encoding='utf-8')
        target = render_kiani_png(kind, text, args.output_dir / (kind + '.png'), now=SAMPLE_TIME, demo=True)
        images.append((kind, target))
        print('RENDERED', kind, flush=True)
    if args.skip_sheet:
        return
    from PIL import Image, ImageDraw
    width, gap, title = 390, 14, 28
    thumbs = []
    for kind, path in images:
        im = Image.open(path).convert('RGB')
        im.thumbnail((width, 600))
        thumbs.append((kind, im))
    height = max(im.height for _, im in thumbs)
    sheet = Image.new('RGB', (width * 2 + gap * 3, (height + title) * 2 + gap * 3), '#d9e3dd')
    draw = ImageDraw.Draw(sheet)
    for index, (kind, im) in enumerate(thumbs):
        x, y = gap + (index % 2) * (width + gap), gap + (index // 2) * (height + title + gap)
        draw.text((x + 6, y + 6), kind, fill='#173f34')
        sheet.paste(im, (x, y + title))
    sheet.save(args.output_dir / 'phone-proof.png')


if __name__ == '__main__':
    main()

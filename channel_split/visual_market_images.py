#!/usr/bin/env python3
"""Deterministic, watermarked USDT proof and reference comparison. Never sends.

Optional comparison dependency: Pillow. The production renderer needs only
Playwright; no image-generation API, Pillow, or network is used for publishing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_images import render_png
from test_market_images import SAMPLES, SAMPLE_TIME
REGIONS = {
    'header': (0, 0, 1200, 132),
    'title': (0, 132, 1200, 318),
    'table': (20, 318, 1180, 1024),
    'summaries': (20, 1046, 1180, 1396),
    'footer': (0, 1416, 1200, 1500),
}


def compare(reference: Path, output: Path, destination: Path, *, demo: bool = True,
            before: Path | None = None) -> dict:
    from PIL import Image, ImageChops, ImageDraw, ImageStat

    size = (1200, 1500)
    reference_image = Image.open(reference).convert('RGB').resize(size, Image.Resampling.LANCZOS)
    rendered = Image.open(output).convert('RGB')
    if demo:
        # Only remove the dedicated, normal-flow 40 CSS-pixel TEST label.
        # Never mask any market field or geometric mismatch from the comparison.
        banner = round(40 * rendered.width / 1200)
        rendered = rendered.crop((0, banner, rendered.width, rendered.height))
    rendered = rendered.resize(size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(reference_image, rendered)
    overlay = Image.blend(reference_image, rendered, .5)
    heatmap = difference.point(lambda value: min(255, value * 4))
    metrics = {}
    for name, box in {'whole': (0, 0, *size), **REGIONS}.items():
        mean = sum(ImageStat.Stat(difference.crop(box)).mean) / 3
        metrics[name] = {'mean_absolute_rgb_error': round(mean, 3), 'fraction_of_255': round(mean / 255, 5)}
    destination.mkdir(parents=True, exist_ok=True)
    overlay.save(destination / 'reference-overlay.png')
    heatmap.save(destination / 'reference-difference.png')
    panels = [('Approved reference', reference_image)]
    if before:
        panels.append(('Previous Telegram output (TEST)', Image.open(before).convert('RGB').resize(size, Image.Resampling.LANCZOS)))
    panels.append(('Rebuilt output (TEST; banner excluded)', rendered))
    sheet = Image.new('RGB', (len(panels) * 600, 790), '#eceef5')
    draw = ImageDraw.Draw(sheet)
    for index, (label, panel) in enumerate(panels):
        draw.text((index * 600 + 14, 12), label, fill='#151538')
        sheet.paste(panel.resize((600, 750), Image.Resampling.LANCZOS), (index * 600, 40))
    sheet.save(destination / 'reference-before-after.png')
    result = {
        'comparison_size': list(size),
        'test_banner_excluded': demo,
        'note': 'RGB error is diagnostic, not a visual-acceptance threshold. Different fonts, reference illustration artifacts, and dynamic timestamps affect it.',
        'regions': metrics,
    }
    if before:
        previous = Image.open(before).convert('RGB').resize(size, Image.Resampling.LANCZOS)
        previous_difference = ImageChops.difference(reference_image, previous)
        result['previous_output_regions'] = {
            name: {'mean_absolute_rgb_error': round(sum(ImageStat.Stat(previous_difference.crop(box)).mean) / 3, 3)}
            for name, box in {'whole': (0, 0, *size), **REGIONS}.items()
        }
    (destination / 'visual-metrics.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, help='User-supplied approved artwork (never a production background)')
    parser.add_argument('--before', type=Path, help='Previous Telegram preview, for the comparison sheet')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / 'usdt-after.png'
    render_png('usdt', SAMPLES['usdt'], output, demo=True, now=SAMPLE_TIME)
    print(f'Watermarked fixture: {output}')
    if args.reference:
        print(json.dumps(compare(args.reference, output, args.output_dir, before=args.before), indent=2))


if __name__ == '__main__':
    main()

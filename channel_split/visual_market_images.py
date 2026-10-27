#!/usr/bin/env python3
"""Deterministic, watermarked report proofs and reference comparisons. Never sends.

Optional comparison dependency: Pillow. The production renderer needs only
Playwright; no image-generation API, Pillow, or network is used for publishing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_images import render_png, SUPPORTED_MARKETS
from test_market_images import SAMPLES, SAMPLE_TIMES
from market_report_templates import ARTBOARDS
REGIONS = {
    'header': (0, 0, 1200, 132),
    'title': (0, 132, 1200, 318),
    'table': (20, 318, 1180, 1024),
    'summaries': (20, 1046, 1180, 1396),
    'footer': (0, 1416, 1200, 1500),
}


def compare(reference: Path, output: Path, destination: Path, *, demo: bool = True,
            before: Path | None = None, kind: str = 'usdt') -> dict:
    from PIL import Image, ImageChops, ImageDraw, ImageStat

    size = (1200, 1500) if kind == 'usdt' else ARTBOARDS[kind]
    if kind == 'usdt':
        regions = REGIONS
    else:
        title_end = {'iran-fx':272,'iran-gold':240,'turkey-gold':272,'fx-pulse':290}[kind]
        regions = {'header':(0,0,1200,140 if kind=='iran-fx' else 116),
                   'title':(0,140 if kind=='iran-fx' else 116,1200,title_end),
                   'content':(20,title_end,1180,size[1]-100),
                   'footer':(0,size[1]-88,1200,size[1])}
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
    for name, box in {'whole': (0, 0, *size), **regions}.items():
        mean = sum(ImageStat.Stat(difference.crop(box)).mean) / 3
        metrics[name] = {'mean_absolute_rgb_error': round(mean, 3), 'fraction_of_255': round(mean / 255, 5)}
    destination.mkdir(parents=True, exist_ok=True)
    overlay.save(destination / 'reference-overlay.png')
    heatmap.save(destination / 'reference-difference.png')
    panels = [('Approved reference', reference_image)]
    if before:
        panels.append(('Previous output (TEST)', Image.open(before).convert('RGB').resize(size, Image.Resampling.LANCZOS)))
    panels.append(('Rebuilt output (TEST; banner excluded)', rendered))
    panel_height = round(size[1]/2)
    sheet = Image.new('RGB', (len(panels) * 600, panel_height + 40), '#eceef5')
    draw = ImageDraw.Draw(sheet)
    for index, (label, panel) in enumerate(panels):
        draw.text((index * 600 + 14, 12), label, fill='#151538')
        sheet.paste(panel.resize((600, panel_height), Image.Resampling.LANCZOS), (index * 600, 40))
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
            for name, box in {'whole': (0, 0, *size), **regions}.items()
        }
    (destination / 'visual-metrics.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('all', *sorted(SUPPORTED_MARKETS)), default='usdt')
    parser.add_argument('--reference', type=Path, help='User-supplied approved artwork (never a production background)')
    parser.add_argument('--before', type=Path, help='Previous Telegram preview, for the comparison sheet')
    parser.add_argument('--reference-dir', type=Path, help='Directory with <kind>/approved-reference.png and optional before.png')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    kinds = sorted(SUPPORTED_MARKETS) if args.kind == 'all' else (args.kind,)
    for kind in kinds:
        folder = args.output_dir/kind if args.kind == 'all' else args.output_dir
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / f'{kind}-after.png'
        render_png(kind, SAMPLES[kind], output, demo=True, now=SAMPLE_TIMES[kind])
        print(f'Watermarked fixture: {output}')
        reference = args.reference or (args.reference_dir/kind/'approved-reference.png' if args.reference_dir else None)
        before = args.before or (args.reference_dir/kind/'before.png' if args.reference_dir else None)
        if reference and reference.is_file():
            metrics=compare(reference, output, folder, before=before if before and before.is_file() else None, kind=kind)
            print(kind, 'RGB diagnostic:', metrics['regions']['whole']['mean_absolute_rgb_error'])


if __name__ == '__main__':
    main()

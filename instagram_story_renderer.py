"""Fit the first, already-published Feed slide into a branded 9:16 Story."""
from pathlib import Path
import xml.etree.ElementTree as ET

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont, ImageOps

LABELS = {
    'rates': 'نرخ امروز', 'economy': 'خبر اقتصادی',
    'top50': 'قیمت ارزهای دیجیتال', 'crypto': 'خبر کریپتو',
}


def render_story(source, destination, asset_root, kind):
    """Keep the complete slide and its original prices, text and timestamps."""
    asset_root, destination = Path(asset_root), Path(destination)
    with Image.open(source) as original:
        if original.format != 'JPEG' or original.width * original.height > 20_000_000:
            raise ValueError('Expected a bounded JPEG Feed slide')
        slide = ImageOps.contain(original.convert('RGB'), (1016, 1350), Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', (1080, 1920), '#EDF4EF')
    draw = ImageDraw.Draw(canvas)

    def font(size, bold=False):
        name = 'Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf'
        return ImageFont.truetype(str(asset_root / 'fonts' / name), size,
                                  layout_engine=ImageFont.Layout.BASIC)

    def fa(text, xy, size, bold=False, fill='#173D32'):
        draw.text(xy, get_display(arabic_reshaper.reshape(text), base_dir='R'),
                  font=font(size, bold), fill=fill, anchor='mm')

    root = ET.parse(asset_root / 'assets/instagram/kiani-logo.svg').getroot()
    _, _, width, height = map(float, root.attrib['viewBox'].split())
    logo = Image.new('RGBA', (384, 384))
    pen = ImageDraw.Draw(logo)
    for node in root.iter('{http://www.w3.org/2000/svg}polygon'):
        points = [tuple(map(float, pair.split(','))) for pair in node.attrib['points'].split()]
        pen.polygon([(x * 384/width, y * 384/height) for x, y in points], fill='#173D32')
    logo = logo.resize((58, 60), Image.Resampling.LANCZOS)
    canvas.paste(logo, (918, 170), logo)
    fa('صرافی کیانی', (785, 196), 35, True)
    draw.text((96, 196), 'kiani.exchange', font=font(29, True), fill='#1C8C67', anchor='lm')
    fa(LABELS[kind] + ' | پست جدید', (540, 268), 29, fill='#708078')
    left = (1080 - slide.width) // 2
    top = 330 + (1350 - slide.height) // 2
    canvas.paste(slide, (left, top))
    fa('پست کامل را در پروفایل ببینید', (540, 1740), 39, True, '#1C8C67')
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, 'JPEG', quality=94, optimize=True)
    destination.chmod(0o644)
    return destination

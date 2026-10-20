"""Approved Kiani gold/coin board, rendered deterministically from checked prices."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from instagram_economic_calendar_renderer import labels, DIGITS, INK, GREEN, MUTED, BG
from iran_gold_data import TEHRAN


def render(snapshot, output, asset_root, *, preview=False):
    if snapshot.get('layout_sample') and not preview:
        raise ValueError('Layout samples cannot produce publication images.')
    output, asset_root = Path(output), Path(asset_root)
    output.mkdir(parents=True, exist_ok=True)
    fonts = {}
    def font(size, bold=False):
        key = size, bold
        if key not in fonts:
            fonts[key] = ImageFont.truetype(str(asset_root / 'fonts' / ('Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf')),
                                           size, layout_engine=ImageFont.Layout.BASIC)
        return fonts[key]
    def fa(draw, text, xy, size, bold=False, fill=INK, anchor='rm', width=None):
        value = get_display(arabic_reshaper.reshape(str(text).translate(DIGITS)), base_dir='R')
        while width and draw.textlength(value, font=font(size, bold)) > width and size > 19:
            size -= 1
        if width and draw.textlength(value, font=font(size, bold)) > width:
            raise ValueError('Gold board text does not fit the reviewed layout.')
        draw.text(xy, value, font=font(size, bold), fill=fill, anchor=anchor)
    image = Image.new('RGB', (1080, 1350), BG)
    draw = ImageDraw.Draw(image)
    root = ET.parse(asset_root / 'assets/instagram/kiani-logo.svg').getroot()
    _, _, lw, lh = map(float, root.attrib['viewBox'].split())
    logo = Image.new('RGBA', (300, 310)); pen = ImageDraw.Draw(logo)
    for node in root.iter('{http://www.w3.org/2000/svg}polygon'):
        points = [tuple(map(float, p.split(','))) for p in node.attrib['points'].split()]
        pen.polygon([(x * 300 / lw, y * 310 / lh) for x, y in points], fill=INK)
    logo = logo.resize((58, 60), Image.Resampling.LANCZOS)
    if preview:
        draw.rectangle((0, 0, 1080, 51), fill='#A87322')
        fa(draw, 'نمونه طراحی • نرخ لحظه‌ای نیست' if snapshot.get('layout_sample') else 'پیش‌نمایش؛ چیزی منتشر نشده است',
           (540, 25), 25, True, 'white', 'mm')
    draw.rounded_rectangle((64, 72, 1016, 84), 6, fill='#D4E6DA')
    draw.rounded_rectangle((820, 72, 1016, 84), 6, fill=GREEN)
    image.paste(logo, (958, 108), logo)
    fa(draw, 'صرافی کیانی', (944, 141), 31, True)
    draw.text((64, 141), 'kiani.exchange', font=font(31, True), fill=GREEN, anchor='lm')
    fa(draw, 'طلا و سکه ایران', (540, 243), 66, True, anchor='mm', width=940)
    fa_date, en_date, _ = labels(datetime.fromisoformat(snapshot['generated_at']), asset_root)
    fa(draw, fa_date, (540, 313), 27, anchor='mm', fill=MUTED)
    draw.text((540, 350), en_date, font=font(23), fill=MUTED, anchor='mm')
    fa(draw, 'قیمت بازار • تومان', (540, 394), 29, anchor='mm', fill=MUTED)
    draw.rounded_rectangle((50, 430, 1030, 485), 18, fill='#DDECE4')
    for text, x, width in [('نوع', 1005, 220), ('قیمت (تومان)', 630, 265), ('۲۴ ساعت', 345, 150), ('۱ ماه', 145, 155)]:
        fa(draw, text, (x, 458), 25, True, anchor='mm' if text != 'نوع' else 'rm', width=width)
    for i, row in enumerate(snapshot['rows']):
        y = 496 + i * 76 + (48 if i >= 5 else 0)
        if i == 5:
            draw.rounded_rectangle((50, y - 46, 1030, y - 9), 18, fill='#F5EDD8')
            fa(draw, 'طلا', (540, y - 27), 28, True, '#A87322', 'mm')
        draw.rounded_rectangle((50, y, 1030, y + 68), 20, fill='white' if i % 2 == 0 else '#E4EFE7')
        fa(draw, row['name'], (1006, y + 34), 30, True, width=249)
        fa(draw, f"{int(Decimal(row['price'])):,}", (630, y + 34), 34, True, anchor='mm', width=300)
        for key, x in [('day', 345), ('month', 145)]:
            value = row[key]
            if value is None:
                fa(draw, '—', (x, y + 34), 29, anchor='mm', fill=MUTED)
            else:
                parsed = Decimal(value)
                color = GREEN if parsed >= 0 else '#BD534D'
                # Isolate financial signs/percentages as LTR; prices and date use Persian digits.
                draw.text((x, y + 34), f'{parsed:+.2f}%', font=font(27, True), fill=color, anchor='mm')
    draw.rounded_rectangle((50, 1110, 1030, 1168), 18, fill='white')
    fa(draw, '— یعنی سابقه معتبر برای مقایسه موجود نیست', (540, 1139), 24, anchor='mm', fill=MUTED, width=940)
    oldest = min(datetime.fromisoformat(x['updated_at']) for x in [*snapshot['primary'].values(), *snapshot['secondary'].values()]).astimezone(TEHRAN)
    clock = oldest.strftime('%H:%M').translate(DIGITS)
    fa(draw, 'قدیمی‌ترین نرخ منبع: ' + clock + ' تهران', (540, 1205), 25, anchor='mm', fill=MUTED)
    fa(draw, 'قیمت‌ها صرفاً جهت اطلاع‌رسانی است.', (540, 1245), 25, anchor='mm', fill=MUTED)
    draw.line((64, 1280, 1016, 1280), fill='#D5E4DA', width=2)
    draw.text((64, 1310), 'Sources: TGJU + DolarChand', font=font(22), fill=MUTED, anchor='lm')
    draw.text((1016, 1310), 'kiani.exchange', font=font(24, True), fill=GREEN, anchor='rm')
    prefix = 'kiani-iran-gold-' + datetime.fromisoformat(snapshot['generated_at']).astimezone(TEHRAN).strftime('%Y%m%d-%H%M%S-')
    path = output / (prefix + uuid.uuid4().hex[:8] + '.jpg')
    image.save(path, 'JPEG', quality=95, subsampling=0)
    path.chmod(0o644)
    return [str(path.resolve())]


def caption(snapshot, asset_root):
    fa_date, en_date, clock = labels(datetime.fromisoformat(snapshot['generated_at']), asset_root)
    lines = ['صرافی کیانی | طلا و سکه ایران', fa_date + '\n' + en_date,
             'قیمت بازار به تومان؛ نرخ مبنا TGJU پس از تطبیق با DolarChand.']
    for row in snapshot['rows']:
        changes = ['—' if row[k] is None else f'{Decimal(row[k]):+.2f}%' for k in ('day', 'month')]
        lines.append(f"{row['name']}: {int(Decimal(row['price'])):,}\n۲۴ ساعت / ۳۰ روز: {' / '.join(changes)}")
    oldest = min(datetime.fromisoformat(x['updated_at']) for x in [*snapshot['primary'].values(), *snapshot['secondary'].values()]).astimezone(TEHRAN)
    lines.extend(['زمان بررسی: ' + clock + ' تهران\nقدیمی‌ترین نرخ منبع: ' + oldest.strftime('%H:%M') + ' تهران',
                  '— یعنی سابقه تأییدشده برای مقایسه نداریم. تغییرات از پست‌های موفق قبلی، نزدیک به ۲۴ ساعت و ۳۰ روز، محاسبه می‌شوند.',
                  'قیمت‌ها صرفاً جهت اطلاع‌رسانی است.\nhttps://www.tgju.org/gold-chart\nhttps://dolarchand.com/en/gold-silver',
                  'kiani.exchange'])
    return '\n\n'.join(lines)

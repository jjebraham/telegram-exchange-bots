"""Approved global-metals layout; explicit USD decimals and signed comparisons."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from instagram_economic_calendar_renderer import labels, DIGITS, INK, GREEN, MUTED, BG
from iran_gold_data import TEHRAN


def fixed(value):
    return f"{Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP):,.2f}"


def bars(image, x, y, size, silver=False):
    layer = Image.new('RGBA',(size*4,size*4))
    draw = ImageDraw.Draw(layer)
    colors = ('#E9EEF0', '#B6BEC2', '#929CA2') if silver else ('#FFED84', '#FFC32A', '#E6A21B')
    def single(a, b):
        def poly(points, fill):
            draw.polygon([((a+px)*size/25, (b+py)*size/25) for px,py in points], fill=fill)
        poly([(0,22),(30,0),(57,9),(27,32)], colors[0])
        poly([(0,22),(27,32),(25,55),(-2,43)], colors[1])
        poly([(27,32),(57,9),(55,32),(25,55)], colors[2])
    single(5,35); single(40,42); single(24,0)
    layer = layer.resize((size,size),Image.Resampling.LANCZOS)
    image.paste(layer,(x,y),layer)


def render(snapshot, output, asset_root, *, preview=False):
    if snapshot.get('layout_sample') and not preview:
        raise ValueError('A global-metals layout sample cannot be published.')
    if len(snapshot.get('rows', [])) != 2:
        raise ValueError('Both verified global metals are required for this slide.')
    asset_root, output = Path(asset_root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    fonts = {}
    def font(size, bold=False):
        if (size,bold) not in fonts:
            fonts[size,bold] = ImageFont.truetype(str(asset_root/'fonts'/('Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf')),
                size, layout_engine=ImageFont.Layout.BASIC)
        return fonts[size,bold]
    def fa(text, xy, size, bold=False, fill=INK, anchor='rm', width=None):
        value = get_display(arabic_reshaper.reshape(text), base_dir='R')
        while width and draw.textlength(value,font=font(size,bold)) > width and size>19:
            size -= 1
        if width and draw.textlength(value,font=font(size,bold)) > width:
            raise ValueError('Global-metals text does not fit the approved layout.')
        draw.text(xy,value,font=font(size,bold),fill=fill,anchor=anchor)
    image = Image.new('RGB',(1080,1350),BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((64,72,1016,84),6,fill='#D4E6DA')
    draw.rounded_rectangle((820,72,1016,84),6,fill=GREEN)
    root = ET.parse(asset_root/'assets/instagram/kiani-logo.svg').getroot()
    _,_,lw,lh = map(float,root.attrib['viewBox'].split())
    logo = Image.new('RGBA',(300,310)); pen = ImageDraw.Draw(logo)
    for node in root.iter('{http://www.w3.org/2000/svg}polygon'):
        points = [tuple(map(float,p.split(','))) for p in node.attrib['points'].split()]
        pen.polygon([(x*300/lw,y*310/lh) for x,y in points],fill=INK)
    logo = logo.resize((58,60),Image.Resampling.LANCZOS)
    image.paste(logo,(958,108),logo)
    fa('صرافی کیانی',(944,141),31,True)
    draw.text((64,141),'kiani.exchange',font=font(31,True),fill=GREEN,anchor='lm')
    if preview:
        draw.rounded_rectangle((425,111,655,151),20,fill='#D4E6DA')
        fa('نمونه طراحی' if snapshot.get('layout_sample') else 'پیش‌نمایش',(540,131),23,anchor='mm')
    fa('بازار جهانی',(540,220),60,True,anchor='mm')
    fa('فلزات گران‌بها',(540,291),60,True,anchor='mm',width=960)
    fa_date,en_date,_ = labels(datetime.fromisoformat(snapshot['generated_at']),asset_root)
    fa(fa_date,(540,354),26,fill=MUTED,anchor='mm')
    draw.text((540,390),en_date,font=font(23),fill=MUTED,anchor='mm')
    fa('قیمت هر اونس تروا (دلار آمریکا)',(540,434),27,fill=MUTED,anchor='mm')
    for i,row in enumerate(snapshot['rows']):
        top = 475+i*238
        draw.rounded_rectangle((50,top,1030,top+220),24,fill='white')
        bars(image,914,top+25,95,silver=i==1)
        fa(row['name'],(897,top+54),37,True,width=310)
        draw.text((897,top+95),'XAU / USD' if i==0 else 'XAG / USD',font=font(23),fill=MUTED,anchor='rm')
        price = '$ '+fixed(row['price'])
        size = 68
        while draw.textlength(price,font=font(size,True))>570:
            size -= 1
        draw.text((88,top+68),price,font=font(size,True),fill=INK,anchor='lm')
        draw.line((85,top+128,996,top+128),fill='#DDECE4',width=2)
        draw.line((540,top+151,540,top+193),fill='#DDECE4',width=2)
        for key,label,cx,lx in [('day','روزانه',728,961),('week','هفتگی',244,463)]:
            value = row.get(key)
            color = MUTED if value is None else GREEN if Decimal(value)>=0 else '#C13A36'
            fill = '#F1F5F2' if value is None else '#E5F2E9' if Decimal(value)>=0 else '#FCE8E8'
            draw.rounded_rectangle((cx-108,top+148,cx+108,top+202),17,fill=fill)
            text = '—' if value is None else f"{Decimal(value):+.2f}%"
            draw.text((cx,top+175),text,font=font(31,True),fill=color,anchor='mm')
            fa(label,(lx,top+175),27,fill=MUTED)
    draw.rounded_rectangle((50,965,1030,1170),24,fill='#E3F0E9')
    bars(image,845,1010,90); bars(image,910,1057,82,True)
    fa('نسبت طلا به نقره',(510,1006),34,True,anchor='mm')
    ratio = fixed(snapshot['ratio'])
    draw.text((510,1071),ratio,font=font(73,True),fill=INK,anchor='mm')
    fa('ارزش ۱ اونس طلا ≈ '+ratio+' اونس نقره',(510,1135),24,fill=MUTED,anchor='mm',width=780)
    clocks = [datetime.fromisoformat(snapshot['providers'][p][row['id']]['updated_at']) for row in snapshot['rows'] for p in row['sources']]
    oldest = min(clocks).astimezone(TEHRAN)
    fa('قدیمی‌ترین نرخ منبع: '+oldest.strftime('%H:%M').translate(DIGITS)+' تهران',(540,1207),24,fill=MUTED,anchor='mm')
    fa('قیمت‌ها صرفاً جهت اطلاع‌رسانی است.',(540,1244),24,fill=MUTED,anchor='mm')
    draw.line((64,1280,1016,1280),fill='#D5E4DA',width=2)
    fa('بازار جهانی',(64,1310),24,fill=MUTED,anchor='lm')
    fa('۲ / ۲',(540,1310),22,fill=MUTED,anchor='mm')
    draw.text((1016,1310),'kiani.exchange',font=font(24,True),fill=GREEN,anchor='rm')
    path = output/('kiani-global-metals-'+datetime.fromisoformat(snapshot['generated_at']).astimezone(TEHRAN).strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]+'.jpg')
    image.save(path,'JPEG',quality=95,subsampling=0); path.chmod(0o644)
    return [str(path.resolve())]


def caption(snapshot):
    lines = ['بازار جهانی فلزات گران‌بها | دلار آمریکا به ازای هر اونس تروا']
    for r in snapshot['rows']:
        changes = ['—' if r.get(k) is None else f"{Decimal(r[k]):+.2f}%" for k in ('day','week')]
        lines.append(r['name']+': $'+fixed(r['price'])+' | روزانه / هفتگی: '+' / '.join(changes))
    lines.append('نسبت طلا به نقره: '+fixed(snapshot['ratio']))
    return '\n'.join(lines)

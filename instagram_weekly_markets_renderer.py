"""Native 1080x1350 weekly comparison in the approved Kiani design."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import math
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from instagram_economic_calendar_renderer import labels, DIGITS, INK, GREEN, MUTED, BG
from weekly_market_data import KINDS, TEHRAN, VERSION


def render(snapshot, output, assets, *, preview=False):
    sample=snapshot.get('layout_sample') is True
    if sample and not preview: raise ValueError('A layout sample cannot be published.')
    rows=snapshot.get('rows',[])
    if (len(rows)!=5 or {r['id'] for r in rows}!=set(KINDS) or
            snapshot.get('unit')!='toman' or snapshot.get('version')!=VERSION):
        raise ValueError('Five exact toman returns are required.')
    changes=[Decimal(r['change_pct']) for r in rows]
    if any(not x.is_finite() or x<=-100 for x in changes) or changes!=sorted(changes,reverse=True):
        raise ValueError('Weekly returns must be finite and ranked by unrounded value.')
    assets,output=Path(assets),Path(output); output.mkdir(parents=True,exist_ok=True)
    im=Image.new('RGB',(1080,1350),BG); d=ImageDraw.Draw(im); fonts={}
    def font(size,bold=False):
        if (size,bold) not in fonts:
            fonts[size,bold]=ImageFont.truetype(str(assets/'fonts'/('Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf')),size,layout_engine=ImageFont.Layout.BASIC)
        return fonts[size,bold]
    def fa(text,xy,size,bold=False,fill=INK,anchor='mm',width=970):
        text=get_display(arabic_reshaper.reshape(text),base_dir='R')
        while d.textlength(text,font=font(size,bold))>width and size>18: size-=1
        if d.textlength(text,font=font(size,bold))>width: raise ValueError('Weekly Persian text does not fit.')
        d.text(xy,text,font=font(size,bold),fill=fill,anchor=anchor)
    def en(text,xy,size,bold=False,fill=INK,anchor='mm',width=None):
        while width and d.textlength(text,font=font(size,bold))>width and size>16: size-=1
        if width and d.textlength(text,font=font(size,bold))>width: raise ValueError('Weekly number does not fit.')
        d.text(xy,text,font=font(size,bold),fill=fill,anchor=anchor)
    d.rounded_rectangle((64,67,1016,79),6,fill='#D4E6DA'); d.rounded_rectangle((820,67,1016,79),6,fill=GREEN)
    root=ET.parse(assets/'assets/instagram/kiani-logo.svg').getroot()
    _,_,w,h=map(float,root.attrib['viewBox'].split()); logo=Image.new('RGBA',(300,310)); pen=ImageDraw.Draw(logo)
    for node in root.iter('{http://www.w3.org/2000/svg}polygon'):
        pts=[tuple(map(float,p.split(','))) for p in node.attrib['points'].split()]
        pen.polygon([(x*300/w,y*310/h) for x,y in pts],fill=INK)
    logo=logo.resize((58,60),Image.Resampling.LANCZOS); im.paste(logo,(958,108),logo)
    fa('صرافی کیانی',(944,139),31,True,anchor='rm',width=240)
    en('kiani.exchange',(64,139),30,True,GREEN,'lm')
    if preview:
        d.rounded_rectangle((350,107,730,152),20,fill='#FFF0BF')
        fa('نمونه طراحی • داده‌های فرضی' if sample else 'پیش‌نمایش تأییدشده',(540,129),22,width=360)
    fa('این هفته کدام بازار',(540,223),59,True)
    fa('بیشتر رشد کرد؟',(540,298),59,True)
    fa('مقایسه بازدهی هفتگی بازارها',(540,372),34,True)
    start,end=[datetime.fromisoformat(snapshot[k]).astimezone(TEHRAN) for k in ('window_start','window_end')]
    a,b=labels(start,assets),labels(end,assets)
    # Full start/end dates remain clear across month/year boundaries.
    fa(a[0].split(' · ',1)[-1]+' تا '+b[0].split(' · ',1)[-1],(540,421),25,fill=MUTED)
    en(start.strftime('%d %b %Y')+' — '+end.strftime('%d %b %Y'),(540,457),22,fill=MUTED)
    fa('مبنای مقایسه: تومان | ساعت ۲۰:۰۰ تهران در هر دو تاریخ',(540,500),25,fill=MUTED)
    d.rounded_rectangle((40,533,1040,1003),25,fill='white')
    low=min(Decimal('0'),min(changes)); high=max(Decimal('0'),max(changes))
    extent=max(abs(low),abs(high),Decimal('1'))
    # Four intervals and one shared linear scale; never normalize each bar separately.
    power=Decimal(10)**int(math.floor(math.log10(float(extent/4))))
    step=next(k*power for k in (Decimal('1'),Decimal('2'),Decimal('2.5'),Decimal('5'),Decimal('10')) if k*power>=extent/4)
    axis_low=(low/step).to_integral_value(rounding='ROUND_FLOOR')*step
    axis_high=(high/step).to_integral_value(rounding='ROUND_CEILING')*step
    if axis_low==axis_high: axis_high=axis_low+step
    left,right=280,775
    def x(v): return left+float((v-axis_low)/(axis_high-axis_low))*(right-left)
    tick=axis_low
    while tick<=axis_high:
        px=x(tick)
        d.line((px,584,px,975),fill='#D8E5DE' if tick else '#90ADA0',width=2 if tick==0 else 1)
        en(f'{tick:+g}%' if tick else '0%',(px,562),18,fill=MUTED)
        tick+=step
    zero=x(Decimal(0))
    for i,row in enumerate(rows):
        y=625+i*80; value=Decimal(row['change_pct']); display=value.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        if display==0: display=abs(display)
        color=GREEN if value>0 else '#C13A36' if value<0 else MUTED
        if i: d.line((62,y-40,1018,y-40),fill='#E7EDE9',width=1)
        en(f'{display:+.2f}%',(235,y),43,True,color,'rm',width=180)
        if value:
            endpoint=x(value); lo,hi=sorted((zero,endpoint))
            d.rounded_rectangle((lo,y-14,max(lo+1,hi),y+14),5,fill=color)
        fa(row['name'],(935,y),30,True,anchor='rm',width=155)
        icon_x=950; icon_y=y-29
        if row['id'] in {'emami','gold18'}:
            path=Path(__file__).parent/'assets/instagram'/('gold-coin.png' if row['id']=='emami' else 'gold-bars.png')
            with Image.open(path) as original: icon=original.convert('RGBA').resize((60,60),Image.Resampling.LANCZOS)
            im.paste(icon,(icon_x,icon_y),icon)
        elif row['id']=='eth':
            cx,cy=icon_x+30,y
            d.polygon([(cx,cy-31),(cx-23,cy+4),(cx,cy+15)],fill='#8B90A7')
            d.polygon([(cx,cy-31),(cx+23,cy+4),(cx,cy+15)],fill='#575F7A')
            d.polygon([(cx-23,cy+10),(cx,cy+33),(cx,cy+20)],fill='#ADB4C7')
            d.polygon([(cx+23,cy+10),(cx,cy+33),(cx,cy+20)],fill='#6B738C')
        else:
            d.ellipse((icon_x,icon_y,icon_x+60,icon_y+60),fill='#F49B23' if row['id']=='btc' else '#3B9974')
            en('B' if row['id']=='btc' else '$',(icon_x+30,y),37,True,'white')
            if row['id']=='btc':
                for xx in (icon_x+24,icon_x+33): d.line((xx,y-23,xx,y+23),fill='white',width=2)
    d.rounded_rectangle((40,1022,1040,1178),25,fill='#E1EFE7')
    best=changes[0]; tied=[r for r in rows if Decimal(r['change_pct'])==best]
    title='بازدهی برابر بازارها' if len(tied)==5 else 'بیشترین رشد این هفته' if best>0 else 'کمترین افت این هفته' if best<0 else 'بهترین عملکرد این هفته'
    fa(title,(540,1063),32,True)
    best_name=('هر پنج بازار' if len(tied)==5 else str(len(tied)).translate(DIGITS)+' بازار با بازدهی یکسان' if len(tied)>2 else ' و '.join(r['name'] for r in tied))
    fa(best_name,(690,1123),34,True,width=450)
    en(f'{best.quantize(Decimal(".01"),rounding=ROUND_HALF_UP):+.2f}%',(300,1123),48,True,GREEN if best>0 else '#C13A36' if best<0 else MUTED,width=240)
    fa('بازدهی رمزارزها پس از تبدیل به تومان محاسبه شده است.',(540,1211),23,fill=MUTED)
    fa('بازدهی قیمت، بدون احتساب کارمزد و اختلاف خرید و فروش',(540,1248),22,fill=MUTED)
    d.line((64,1280,1016,1280),fill='#D4E6DA',width=2)
    fa('داده‌های فرضی؛ صرفاً نمونه طراحی' if sample else 'بازه یکسان • قیمت‌های تأییدشده',(64,1312),21,fill=MUTED,anchor='lm',width=550)
    en('kiani.exchange',(1016,1312),24,True,GREEN,'rm')
    name='kiani-weekly-markets-'+end.strftime('%Y%m%d-')+uuid.uuid4().hex[:10]+'.jpg'
    path=output/name; im.save(path,'JPEG',quality=95,subsampling=0); path.chmod(0o644)
    return [str(path.resolve())]


def caption(snapshot):
    start,end=[datetime.fromisoformat(snapshot[k]).astimezone(TEHRAN) for k in ('window_start','window_end')]
    lines=['مقایسه بازدهی هفتگی بازارها | مبنا: تومان',
           start.strftime('%Y-%m-%d %H:%M')+' تا '+end.strftime('%Y-%m-%d %H:%M')+' تهران']
    for row in snapshot['rows']: lines.append(row['name']+': '+f"{Decimal(row['display_pct']):+.2f}%")
    lines+=['بازدهی = (قیمت پایان ÷ قیمت آغاز − ۱) × ۱۰۰',
            'بیت‌کوین و اتریوم: قیمت دلاری × نرخ دلار همان مشاهده؛ همه قیمت‌ها به تومان.',
            'زمان‌های اصلی منابع در هر مشاهده حداکثر ۱۰ دقیقه اختلاف دارند؛ تطابق هفتگی حداکثر ۵ دقیقه.',
            'بازدهی قیمت است؛ کارمزد و اختلاف خرید و فروش در آن منظور نشده است.',
            'منابع: Servix، CoinPaprika، Alanchand و DolarChand؛ منابع هم‌پوشان ممکن است تأمین‌کننده مشترک داشته باشند.',
            'صرفاً جهت اطلاع‌رسانی. #بازار_طلا #بیت_کوین #اقتصاد #صرافی_کیانی']
    return '\n'.join(lines)

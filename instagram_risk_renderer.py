"""Six readable Persian risk-dashboard pages with explicit data coverage."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from instagram_economic_calendar_renderer import labels
from risk_market_core import ASSETS, METHOD, TEHRAN, VERSION, day, number

INK,GREEN,MUTED,BG='#173D32','#208C68','#708078','#EDF4EF'
DIGITS=str.maketrans('0123456789','۰۱۲۳۴۵۶۷۸۹')
DESCRIPTIONS={
 'gold':'نرخ مرجع طلا به دلار برای هر اونس تروا؛ نزدیک ساعت ۱۷ جمعه نیویورک.',
 'brent':'قیمت نقدی برنت اروپا، به دلار برای هر بشکه؛ منبع EIA.',
 'btc':'نرخ دلاری نزدیک ساعت ۱۷ جمعه نیویورک؛ بازار رمزارز آخر هفته باز است.',
 'vix':'نوسان مورد انتظار سهام آمریکا در حدود ۳۰ روز آینده؛ این عدد احتمال وقوع بحران نیست.',
 'dollar':'شاخص گسترده دلار فدرال رزرو؛ مبنا ژانویه ۲۰۰۶ برابر ۱۰۰. این شاخص DXY نیست.',
 'us10y':'بازده روزانه سررسید ثابت ۱۰ ساله؛ با قیمت اوراق و هر نقل‌قول لحظه‌ای یکسان نیست.',
 'stress':'شاخص هفتگی STLFSI4؛ بالای صفر یعنی تنش بیشتر از میانگین تاریخی و زیر صفر یعنی کمتر.',
}


def fmt(value,digits=2,signed=False):
    if value is None:
        return '—'
    val=number(value).quantize(Decimal(10)**-digits,rounding=ROUND_HALF_UP)
    if val==0:
        val=abs(val)
    return format(val,('+' if signed else '')+',.'+str(digits)+'f')


def value_text(row):
    if row.get('value') is None:
        return '—'
    if row['id'] in {'gold','brent','btc'}:
        return '$'+fmt(row['value'])
    if row['id']=='stress':
        return fmt(row['value'],4)
    return fmt(row['value'])+('%' if row['id']=='us10y' else '')


def change_text(row):
    if row.get('change_points') is None:
        return '—'
    if row['id']=='us10y':
        return fmt(row['change_bps'],0,True)+' bp'
    if row['id'] in {'vix','stress'}:
        return fmt(row['change_points'],4 if row['id']=='stress' else 2,True)+' pt'
    return fmt(row['change_pct'],2,True)+'%'


def caption(snapshot):
    prefix='نمونه طراحی با داده‌های فرضی' if snapshot.get('layout_sample') else 'دماسنج ریسک بازارهای جهانی'
    parts=[prefix,'گزارش آخر هفته '+snapshot['week_end'],snapshot['assessment']['headline']]
    parts += [ASSETS[r['id']]['name']+': '+value_text(r)+' | '+change_text(r)+'\n'+r['previous_date']+' تا '+r['observation_date'] for r in snapshot['rows']]
    parts += ['طلا و بیت‌کوین: نرخ مرجع نزدیک ساعت ۱۷ جمعه نیویورک. هر ردیف تاریخ و تأخیر انتشار خودش را دارد؛ تغییر آن با هفت روز قبل همان مشاهده سنجیده می‌شود.',
              'واحد bp: واحد پایه؛ ۱۰۰ واحد پایه برابر یک واحد درصد است.',
              'این گزارش آموزشی تغییرات مشاهده‌شده را توصیف می‌کند و توصیه خرید یا فروش یا پیش‌بینی بحران نیست.',
              'منابع: Servix، Alanchand/DolarChand، CoinPaprika؛ Cboe (VIX)؛ US EIA (DCOILBRENTEU)؛ Federal Reserve (DTWEXBGS/DGS10)؛ St. Louis Fed (STLFSI4)، از طریق FRED. دو قالب STLFSI4 از یک ناشرند، نه دو منبع مستقل.',
              'kiani.exchange | #بازارهای_جهانی #طلا #نفت #بیت_کوین #اقتصاد']
    if not snapshot.get('all_verified'):
        parts.insert(1,'پیش‌نمایش؛ برای انتشار تأیید نشده است.')
    text='\n\n'.join(parts)
    if len(text)>2200:
        raise ValueError('Risk caption exceeds the Instagram limit.')
    return text


def render(snapshot,output,assets,*,preview=False):
    if snapshot.get('version')!=VERSION or snapshot.get('method')!=METHOD:
        raise ValueError('Unreviewed dashboard version.')
    rows=snapshot.get('rows',[])
    if len(rows)!=7 or {r['id'] for r in rows}!=set(ASSETS):
        raise ValueError('Seven explicit free-data rows are required.')
    if not preview and (snapshot.get('layout_sample') or snapshot.get('all_verified') is not True):
        raise ValueError('Incomplete or sample dashboards cannot be published.')
    assets,output=Path(assets),Path(output)
    output.mkdir(parents=True,exist_ok=True,mode=0o755)
    output.chmod(0o755)
    items={r['id']:r for r in rows};fonts={}
    def font(size,bold=False):
        if (size,bold) not in fonts:
            fonts[size,bold]=ImageFont.truetype(str(assets/'fonts'/('Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf')),
                                             size,layout_engine=ImageFont.Layout.BASIC)
        return fonts[size,bold]
    def shaped(text):
        return get_display(arabic_reshaper.reshape(str(text).translate(DIGITS)),base_dir='R')
    def fa(draw,text,xy,size=44,bold=False,fill=INK,anchor='rt',width=952):
        display=shaped(text)
        if draw.textlength(display,font=font(size,bold))>width:
            raise ValueError('Persian text exceeds the fixed readable width.')
        draw.text(xy,display,font=font(size,bold),fill=fill,anchor=anchor)
    def en(draw,text,xy,size=52,bold=True,fill=INK,anchor='lt',width=900):
        if draw.textlength(text,font=font(size,bold))>width:
            raise ValueError('Number exceeds its readable width.')
        draw.text(xy,text,font=font(size,bold),fill=fill,anchor=anchor)
    def paragraph(draw,text,box,size=44,bold=False,fill=INK):
        left,top,right,bottom=box;lines=[];line=''
        for word in text.split():
            trial=(line+' '+word).strip()
            if line and draw.textlength(shaped(trial),font=font(size,bold))>right-left:
                lines.append(line);line=word
            else:
                line=trial
        if line:
            lines.append(line)
        leading=round(size*1.55)
        if (len(lines)-1)*leading+size>bottom-top:
            raise ValueError('Body exceeds its readable card; add a page rather than shrinking text.')
        for i,line in enumerate(lines):
            fa(draw,line,(right,top+i*leading),size,bold,fill,width=right-left)
    root=ET.parse(assets/'assets/instagram/kiani-logo.svg').getroot()
    _,_,lw,lh=map(float,root.attrib['viewBox'].split())
    logo=Image.new('RGBA',(248,248));pen=ImageDraw.Draw(logo)
    for node in root.iter('{http://www.w3.org/2000/svg}polygon'):
        points=[tuple(map(float,p.split(','))) for p in node.attrib['points'].split()]
        pen.polygon([(x*248/lw,y*248/lh) for x,y in points],fill=INK)
    logo=logo.resize((62,62),Image.Resampling.LANCZOS)
    fa_date,en_date,_=labels(datetime.combine(day(snapshot['week_end']),datetime.min.time(),TEHRAN).replace(hour=12),assets)
    def base(page,title):
        image=Image.new('RGB',(1080,1350),BG);draw=ImageDraw.Draw(image)
        draw.rounded_rectangle((64,55,1016,66),5,fill='#D4E6DA')
        draw.rounded_rectangle((1016-round(952*page/6),55,1016,66),5,fill=GREEN)
        image.paste(logo,(954,108),logo)
        fa(draw,'صرافی کیانی',(934,114),32,True,width=300)
        en(draw,'kiani.exchange',(64,119),29,True,GREEN)
        fa(draw,title,(1016,224),64,True)
        if preview:
            draw.rounded_rectangle((64,302,1016,358),22,fill='#F8E8BB')
            fa(draw,'نمونه طراحی • تمام اعداد فرضی‌اند' if snapshot.get('layout_sample') else 'پیش‌نمایش • داده‌های کامل هنوز تأیید نشده‌اند',
               (540,330),30,True,anchor='mm')
        draw.line((64,1235,1016,1235),fill='#D4E6DA',width=2)
        fa(draw,fa_date,(1016,1260),25,fill=MUTED)
        en(draw,en_date,(64,1260),23,False,MUTED)
        fa(draw,f'{page} از 6',(1016,1312),25,fill=MUTED)
        fa(draw,'دماسنج هفتگی • روش توصیفی',(64,1312),25,fill=MUTED,anchor='lt')
        return image,draw
    frames=[]
    image,draw=base(1,'دماسنج ریسک جهانی')
    paragraph(draw,snapshot['assessment']['headline'],(64,380,1016,480),44,True)
    draw.rounded_rectangle((40,500,1040,1200),25,fill='white')
    fa(draw,'شاخص',(996,526),29,True)
    fa(draw,'مقدار',(600,526),29,True,anchor='mt')
    fa(draw,'تغییر ۷روزه',(280,526),29,True,anchor='mt')
    for i,row in enumerate(rows):
        y=590+i*83
        if i:
            draw.line((64,y-15,1016,y-15),fill='#E1ECE5',width=1)
        name={'us10y':'اوراق ۱۰ ساله','stress':'تنش مالی'}.get(row['id'],ASSETS[row['id']]['short'])
        fa(draw,name,(996,y),38,True,width=330)
        en(draw,value_text(row),(660,y),43,True,anchor='rt',width=340)
        en(draw,change_text(row),(290,y+3),35,True,anchor='rt',width=235)
        en(draw,row['observation_date'],(996,y+47),22,False,MUTED,anchor='rt',width=250)
    frames.append(image)
    def cards(page,title,keys):
        image,draw=base(page,title)
        top=388 if preview else 340
        height=(1185-top-20*(len(keys)-1))//len(keys)
        for index,key in enumerate(keys):
            y=top+index*(height+20);row=items[key]
            draw.rounded_rectangle((64,y,1016,y+height),28,fill='white')
            fa(draw,ASSETS[key]['short'],(972,y+28),44,True,width=380)
            en(draw,value_text(row),(108,y+31),54,width=500)
            en(draw,change_text(row),(108,y+93),35,True,fill=INK)
            if len(keys)==3:
                paragraph(draw,DESCRIPTIONS[key],(108,y+139,972,y+height-10),38)
            else:
                paragraph(draw,DESCRIPTIONS[key],(108,y+159,972,y+height-75),42)
                en(draw,row['observation_date'],(972,y+height-48),26,False,MUTED,anchor='rt')
        return image
    frames.append(cards(2,'طلا، نفت و بیت‌کوین',('gold','brent','btc')))
    frames.append(cards(3,'نوسان و تنش مالی',('vix','stress')))
    frames.append(cards(4,'دلار و بازده اوراق',('dollar','us10y')))
    image,draw=base(5,'تاریخ داده‌ها را ببینید')
    draw.rounded_rectangle((64,388,1016,1197),28,fill='white')
    paragraph(draw,'این گزارش ترکیبی از نرخ بازار و آخرین آمار منتشرشده است؛ همه ردیف‌ها قیمت لحظه‌ای یا داده یک روز نیستند.',
              (108,424,972,642),44,True)
    for i,row in enumerate(rows):
        y=680+i*57
        fa(draw,ASSETS[row['id']]['short'],(972,y),32,True,width=400)
        en(draw,row['previous_date']+' > '+row['observation_date'],(108,y),25,False,MUTED,width=450)
    frames.append(image)
    image,draw=base(6,'جمع‌بندی قابل پیگیری')
    draw.rounded_rectangle((64,388,1016,1038),28,fill='white')
    paragraph(draw,'این هفته چه دیدیم؟',(108,424,972,505),54,True)
    paragraph(draw,snapshot['assessment']['observations'][0],(108,530,972,735),48,True)
    paragraph(draw,'هفت شاخص با تاریخ‌های مشخص؛ بدون امتیاز ساختگی یا پیش‌بینی بحران. افزایش یک شاخص لزوماً پیام مثبتی برای بازار نیست.',
              (108,770,972,1005),42)
    draw.rounded_rectangle((64,1071,1016,1202),24,fill='#F8E8BB')
    paragraph(draw,'گزارش آموزشی است؛ توصیه خرید یا فروش و پیش‌بینی بازار نیست.',(108,1091,972,1188),36)
    frames.append(image)
    prefix='kiani-risk-'+snapshot['week_end'].replace('-','')+'-'+uuid.uuid4().hex[:8]
    paths=[]
    for i,image in enumerate(frames,1):
        path=output/(prefix+f'-{i:02}.jpg');image.save(path,'JPEG',quality=95,subsampling=0)
        path.chmod(0o644)
        paths.append(str(path.resolve()))
    return paths

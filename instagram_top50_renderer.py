"""Four-slide Kiani crypto highlights, drawn from the verified price snapshot."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path
import sys
import uuid
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont
from crypto_top50_data import PricesError, validate_snapshot, select_decliners, timestamp

DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
GREEN, RED, WHITE = '#31D69B', '#FF8588', '#F8FBF9'
NEUTRAL = '#607E73'
GREEN_THEME = {'background': '#0B2C22', 'panel': '#123A2E', 'accent': GREEN, 'muted': '#9AC9B7', 'stroke': '#2C5A48'}
RED_THEME = {'background': '#2D1016', 'panel': '#411B25', 'accent': RED, 'muted': '#CFA4AA', 'stroke': '#63343D'}
SECTIONS = ('market_pulse', 'gainers', 'declines', 'engagement')

NAMES = {
    'lit-lighter': 'لایتر',
    'btc-bitcoin': 'بیت‌کوین', 'eth-ethereum': 'اتریوم', 'bnb-binance-coin': 'بی‌ان‌بی',
    'xrp-xrp': 'ریپل', 'sol-solana': 'سولانا', 'trx-tron': 'ترون', 'zec-zcash': 'زی‌کش',
    'hype-hyperliquid': 'هایپرلیکوئید', 'doge-dogecoin': 'دوج‌کوین', 'xmr-monero': 'مونرو',
    'wbt-whitebit': 'وایت‌بیت', 'link-chainlink': 'چین‌لینک', 'ada-cardano': 'کاردانو',
    'leo-leo-token': 'لئو', 'xlm-stellar': 'استلار', 'near-near-protocol': 'نیر',
    'bch-bitcoin-cash': 'بیت‌کوین کش', 'ltc-litecoin': 'لایت‌کوین', 'cc-canton-network': 'کانتون',
    'uni-uniswap': 'یونی‌سواپ', 'sui-sui': 'سویی', 'avax-avalanche': 'آوالانچ',
    'hbar-hedera-hashgraph': 'هدرا', 'toncoin-the-open-network': 'گرام (تون‌کوین)',
    'shib-shiba-inu': 'شیبا اینو', 'btw-bitway': 'بیت‌وی', 'cro-cryptocom-chain': 'کرونوس',
    'qnt-quant': 'کوانت', 'ena-ethena': 'اتنا', 'okb-okb': 'او‌کی‌بی',
    'tao-bittensor': 'بیت‌تنسور', 'pump-pumpfun': 'پامپ‌فان', 'aave-new': 'آوه',
    'm-memecore': 'میم‌کور', 'ondo-ondo': 'اوندو', 'wld-worldcoin': 'ورلدکوین',
    'mnt-mantle': 'منتل', 'sky-sky': 'اسکای',
    'wlfi-official-world-liberty-financial': 'ورلد لیبرتی',
    'icp-internet-computer': 'اینترنت کامپیوتر', 'pepe-pepe': 'پپه', 'jst-just': 'جاست',
    'bgb-bitget-token': 'بیت‌گت توکن', 'gt-gatechain-token': 'گیت توکن',
    'etc-ethereum-classic': 'اتریوم کلاسیک', 'arb-arbitrum': 'آربیتروم', 'aster-aster': 'استر',
    'jup-jupiter-exchange-token': 'ژوپیتر', 'vvv-venice-token': 'ونیز', 'kas-kaspa': 'کسپا',
    'rain-rain-protocol': 'رین پروتکل', 'ftm-fantom': 'فانتوم', 'agix-singularitynet': 'سینگولاریتی‌نت',
    'pol-polygon-ecosystem-token': 'پالیگان', 'kcs-kucoin-token': 'کوکوین توکن',
    'algo-algorand': 'الگوراند', 'rndr-render-token': 'رندر', 'fil-filecoin': 'فایل‌کوین',
    'atom-cosmos': 'کازماس', 'aero-aerodrome-finance': 'ایرودروم', 'pi2-pi-network': 'پای نتورک',
}

def price_text(value, *, usd=False):
    """Display rounding only; preserve small positive prices rather than show zero."""
    number = Decimal(value)
    if number >= (1 if usd else 10):
        places = 2 if usd else 0
    elif number >= Decimal('0.01'):
        places = 4 if usd else 2
    else:
        places = max(2, 3 - number.adjusted())  # Four significant digits for tiny prices.
    if places > 14:
        return f'{number:.3E}'
    with localcontext() as context:
        context.prec = max(60, len(number.as_tuple().digits) + places + 8)
        rounded = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    text = f'{rounded:,.{places}f}'
    if number < 1:
        text = text.rstrip('0').rstrip('.')
    return text


def significant_gainers(snapshot):
    return [c for c in snapshot['gainers']
            if Decimal(c['change_24h']).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) > 2][:5]


def breadth(snapshot):
    counts = dict(up=0, down=0, flat=0, missing=0)
    for coin in snapshot['coins']:
        change = coin.get('change_24h')
        if change is None:
            counts['missing'] += 1
        else:
            value = Decimal(change)
            counts['up' if value > 0 else 'down' if value < 0 else 'flat'] += 1
    known = sum(counts[k] for k in ('up', 'down', 'flat'))
    state = ('missing' if not known else 'flat' if counts['flat'] == known else
             'green' if counts['up'] * 2 > known else
             'red' if counts['down'] * 2 > known else 'mixed')
    return dict(counts, known=known, total=len(snapshot['coins']), state=state)


def move(value):
    if value is None:
        return '—', NEUTRAL
    number = Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return (f'{number:+.2f}%' if number else '0.00%'), GREEN if number > 0 else RED if number < 0 else NEUTRAL


def calendar_badge(moment, asset_root):
    # Reuse the already installed calendar dependency used by Kiani's other posts.
    library = Path(asset_root) / 'instagram_calendar_libs'
    if library.is_dir() and str(library) not in sys.path:
        sys.path.insert(0, str(library))
    import jdatetime
    day = jdatetime.date.fromgregorian(date=moment.date())
    months = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
              'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')
    weekdays = ('دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه')
    return f'{weekdays[moment.weekday()]} {day.day} {months[day.month - 1]}'


class Card:
    def __init__(self, assets, theme, logo, *, sample=False):
        self.assets, self.theme = assets, theme
        self.image = Image.new('RGB', (1080, 1350), theme['background'])
        self.draw = ImageDraw.Draw(self.image)
        self.fonts = {}
        self.logo = logo
        if sample:
            self.draw.rectangle((0, 0, 1080, 36), fill='#F6D78F')
            self.text('نمونه طراحی · نرخ لحظه‌ای نیست', (540, 18), 20, fa=True, bold=True, fill='#533D13')

    def font(self, size, bold=False):
        key = size, bold
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(str(self.assets / 'fonts' /
                ('Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf')), size,
                layout_engine=ImageFont.Layout.BASIC)
        return self.fonts[key]

    def text(self, value, xy, size, *, fa=False, bold=False, fill=WHITE, anchor='mm', width=None):
        rendered = get_display(arabic_reshaper.reshape(str(value).translate(DIGITS)), base_dir='R') if fa else str(value)
        while width and self.draw.textlength(rendered, font=self.font(size, bold)) > width and size > 18:
            size -= 1
        if width and self.draw.textlength(rendered, font=self.font(size, bold)) > width:
            raise PricesError('A highlights label exceeds its safe card.')
        self.draw.text(xy, rendered, font=self.font(size, bold), fill=fill, anchor=anchor)

    def box(self, rect, fill=None, radius=24, outline=None, width=1):
        self.draw.rounded_rectangle(rect, radius=radius, fill=fill or self.theme['panel'], outline=outline, width=width)

    def header(self, page, date=None):
        self.image.paste(self.logo, (961, 88), self.logo)
        self.text('صرافی کیانی', (932, 110), 34, fa=True, bold=True, fill=WHITE, anchor='rm', width=285)
        if date:
            self.box((64, 77, 348, 145), fill=self.theme['background'], radius=34, outline=self.theme['stroke'], width=2)
            self.text(date, (206, 111), 26, fa=True, bold=True, fill=self.theme['muted'], width=250)
        else:
            self.text(f'{page} / 4', (64, 110), 29, bold=True, fill=self.theme['muted'], anchor='lm')

    def footer(self, prompt, stamp):
        color = self.theme['accent']
        self.draw.line((64, 1256, 96, 1256), fill=color, width=3)
        self.draw.line((64, 1256, 75, 1245), fill=color, width=3)
        self.draw.line((64, 1256, 75, 1267), fill=color, width=3)
        self.text(prompt, (113, 1256), 25, fa=True, bold=True, fill=color, anchor='lm', width=600)
        self.text('kiani.exchange', (1016, 1256), 25, bold=True, fill=self.theme['muted'], anchor='rm')
        self.text(stamp, (1016, 1310), 18, fa=True, fill=self.theme['muted'], anchor='rm', width=952)


def brand_logo(assets):
    root = ET.parse(assets / 'assets/instagram/kiani-logo.svg').getroot()
    _, _, width, height = map(float, root.attrib['viewBox'].split())
    logo = Image.new('RGBA', (180, 184))
    draw = ImageDraw.Draw(logo)
    for node in root.iter('{http://www.w3.org/2000/svg}polygon'):
        points = [tuple(map(float, pair.split(','))) for pair in node.attrib['points'].split()]
        draw.polygon([(x * 180 / width, y * 184 / height) for x, y in points], fill=WHITE)
    return logo.resize((44, 46), Image.Resampling.LANCZOS)


def cover(card, snapshot, stats):
    t, d, th = card.text, card.draw, card.theme
    state = stats['state']
    t('نبض ۲۴ ساعت بازار کریپتو', (1016, 220), 31, fa=True, bold=True, fill=th['muted'], anchor='rm', width=952)
    title = {'green': 'بازار سبزه', 'red': 'بازار قرمزه', 'mixed': 'بازار دو رنگه',
             'flat': 'قیمت‌ها بی‌تغییرند', 'missing': 'داده‌ها کامل نیست'}[state]
    t(title, (1016, 340), 117, fa=True, bold=True, fill=th['accent'], anchor='rm', width=952)
    if state in ('green', 'red'):
        count = stats['up' if state == 'green' else 'down']
        group = f"{stats['known']} ارز دارای داده" if stats['missing'] else f"{stats['total']} ارز برتر"
        message = f'{count} از {group} ' + ('رشد کردند' if state == 'green' else 'افت کردند')
    elif state == 'mixed':
        message = f"{stats['up']} صعودی، {stats['down']} نزولی؛ بازار یک‌دست نیست"
    elif state == 'flat':
        message = 'تغییر ثبت‌شده در ارزهای دارای داده، صفر است'
    else:
        message = 'تغییر ۲۴ ساعته در منبع در دسترس نیست'
    t(message, (1016, 440), 36, fa=True, bold=True, anchor='rm', width=952)
    # Exactly one dot per coin. Missing data is hollow, never counted as flat.
    order = ('down', 'up', 'flat', 'missing') if state == 'red' else ('up', 'down', 'flat', 'missing')
    colors = dict(up=GREEN, down=RED, flat=NEUTRAL, missing=th['stroke'])
    dots = [kind for kind in order for _ in range(stats[kind])]
    for index, kind in enumerate(dots):
        x = 974 - (index % 10) * 96.4
        y = 551 + (index // 10) * 83
        rect = (round(x - 31), y - 31, round(x + 31), y + 31)
        d.ellipse(rect, fill=colors[kind] if kind != 'missing' else None,
                  outline=colors[kind], width=3)
    for x, kind, label in ((1016, 'up', 'صعودی'), (681, 'down', 'نزولی'), (346, 'flat', 'بدون تغییر')):
        d.ellipse((x-20, 944, x, 964), fill=colors[kind])
        t(f"{stats[kind]} {label}", (x-32, 954), 24, fa=True, bold=True, fill=th['muted'], anchor='rm', width=270)
    if stats['missing']:
        t(f"دایره توخالی: {stats['missing']} ارز بدون داده تغییرات", (1016, 994), 20,
          fa=True, fill=th['muted'], anchor='rm', width=952)
    for left, identity, name, symbol in ((556, 'btc-bitcoin', 'بیت‌کوین', 'BTC'), (64, 'eth-ethereum', 'اتریوم', 'ETH')):
        coin = next((c for c in snapshot['coins'] if c['id'] == identity), None)
        value, color = move(coin.get('change_24h') if coin else None)
        card.box((left, 1030, left+460, 1167))
        t(symbol, (left+432, 1073), 36, bold=True, anchor='rm', width=218)
        t(name, (left+432, 1122), 23, fa=True, fill=th['muted'], anchor='rm', width=218)
        t(value, (left+28, 1103), 46, bold=True, fill=color, anchor='lm', width=220)
    t('نمای ۵۰ ارز برتر · تغییر قیمت دلاری · CoinPaprika', (1016, 1203), 20, fa=True, fill=th['muted'], anchor='rm', width=952)


def movers(card, rows, *, losses=False):
    t, d, th = card.text, card.draw, card.theme
    accent = RED if losses else GREEN
    t('بیشترین افت‌های امروز' if losses else 'پیشتازان امروز', (1016, 230), 76,
      fa=True, bold=True, anchor='rm', width=952)
    t('بیش از ۲٪ افت در ۲۴ ساعت · میان ۱۰۰ ارز برتر' if losses else
      'بیش از ۲٪ رشد در ۲۴ ساعت · میان ۱۰۰ ارز برتر', (1016, 300), 28,
      fa=True, bold=True, fill=th['muted'], anchor='rm', width=952)
    maximum = abs(Decimal(rows[0]['change_24h'])) if rows else Decimal(1)
    for index, coin in enumerate(rows):
        top = 351 + index * 170
        card.box((64, top, 1016, top+151))
        d.ellipse((913, top+29, 981, top+97), fill=th['background'])
        t(index+1, (947, top+63), 32, fa=True, bold=True, fill=accent)
        name = NAMES.get(coin['id'], coin['name'])
        t(coin['symbol'], (890, top+47), 42, bold=True, anchor='rm', width=450)
        t(name, (890, top+91), 24, fa=coin['id'] in NAMES, fill=th['muted'], anchor='rm', width=430)
        t(move(coin['change_24h'])[0], (96, top+63), 55, bold=True, fill=accent, anchor='lm', width=300)
        card.box((96, top+123, 984, top+134), fill=th['background'], radius=5)
        ratio = min(Decimal(1), abs(Decimal(coin['change_24h']))/maximum)
        width = max(8, round(float(ratio)*888))
        card.box((984-width, top+123, 984, top+134), fill=accent, radius=5)
    if not rows:
        card.box((64, 365, 1016, 1120))
        t('—', (540, 585), 150, bold=True, fill=th['muted'])
        t('امروز ارزی با این شرایط پیدا نشد', (540, 778), 39, fa=True, bold=True, width=840)
        t('حد نصاب بیش از ۲٪ و فیلترهای منبع حفظ شده‌اند', (540, 846), 26, fa=True, fill=th['muted'], width=840)
    elif len(rows) < 5:
        t(f'فقط {len(rows)} ارز واجد شرایط بود', (1016, 351+len(rows)*170+30), 27,
          fa=True, fill=th['muted'], anchor='rm', width=952)
    t('بدون استیبل‌کوین و توکن رپد · حجم معاملات بیش از ۵۰ هزار دلار', (1016, 1216), 19,
      fa=True, fill=th['muted'], anchor='rm', width=952)


def engagement(card):
    t, d, th = card.text, card.draw, card.theme
    t('سبدت امروز', (1016, 290), 97, fa=True, bold=True, anchor='rm', width=952)
    t('سبز بود', (1016, 420), 103, fa=True, bold=True, fill=GREEN, anchor='rm', width=450)
    green_width = d.textlength(get_display(arabic_reshaper.reshape('سبز بود'), base_dir='R'), font=card.font(103, True))
    t('یا قرمز؟', (1016-green_width-34, 420), 103, fa=True, bold=True, fill=RED, anchor='rm', width=450)
    t('توی کامنت بنویس: «سبز» یا «قرمز»', (1016, 545), 32,
      fa=True, bold=True, fill=th['muted'], anchor='rm', width=952)
    card.box((64, 648, 1016, 763))
    d.line([(944, 680), (972, 680), (972, 727), (958, 716), (944, 727), (944, 680)], fill=GREEN, width=4)
    t('ذخیره کن، فردا مقایسه کن', (912, 705), 35, fa=True, bold=True, anchor='rm', width=790)
    card.box((64, 784, 1016, 899))
    d.line([(940, 839), (978, 817), (967, 865), (955, 847), (978, 817), (947, 843), (940, 839)], fill=GREEN, width=4)
    t('برای دوست علاقه‌مندت به کریپتو بفرست', (912, 841), 31, fa=True, bold=True, anchor='rm', width=790)
    card.box((64, 960, 1016, 1182), fill=GREEN)
    t('نرخ‌های لحظه‌ای ارز', (979, 1003), 28, fa=True, bold=True, fill=th['background'], anchor='rm', width=870)
    t('ربات تلگرام کیانی', (979, 1064), 49, fa=True, bold=True, fill=th['background'], anchor='rm', width=870)
    t('@kianiexchangebot', (979, 1132), 43, bold=True, fill=th['background'], anchor='rm', width=870)


def render(snapshot, output, asset_root):
    validate_snapshot(snapshot)
    if snapshot.get('schema') != 3:
        raise PricesError('The highlights template requires the verified market-pulse snapshot.')
    output, assets = Path(output).resolve(), Path(asset_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    stats = breadth(snapshot)
    local = datetime.fromisoformat(snapshot['generated_at']).astimezone(ZoneInfo('Europe/Istanbul'))
    stamp = f'{local:%Y/%m/%d · %H:%M} استانبول · تغییر ۲۴ ساعته · CoinPaprika'
    date = calendar_badge(local, assets)
    logo = brand_logo(assets)
    classes = snapshot['gainers_classifications']
    losers = select_decliners(snapshot['gainers_candidates'], set(classes['stablecoin']),
        set(classes['wrapped_token']), timestamp(snapshot['generated_at']), sample=bool(snapshot.get('sample')))
    prefix = f'kiani-crypto-highlights-{local:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:10]}'
    paths = []
    for page, section in enumerate(SECTIONS, 1):
        theme = RED_THEME if section == 'declines' or (section == 'market_pulse' and stats['state'] == 'red') else GREEN_THEME
        card = Card(assets, theme, logo, sample=bool(snapshot.get('sample')))
        card.header(page, date if page == 1 else None)
        if section == 'market_pulse':
            cover(card, snapshot, stats)
        elif section in ('gainers', 'declines'):
            movers(card, losers if section == 'declines' else significant_gainers(snapshot), losses=section == 'declines')
        else:
            engagement(card)
        prompt = ('پیشتازهای امروز رو ببین', 'سمت دیگر بازار رو ببین', 'سبدت امروز چه رنگیه؟', 'برای نبض روزانه بازار، همراه ما باش')[page-1]
        card.footer(prompt, stamp)
        path = output / f'{prefix}-{page:02}.jpg'
        card.image.save(path, 'JPEG', quality=95, subsampling=0, optimize=True)
        paths.append(path)
    return paths


def caption(snapshot):
    validate_snapshot(snapshot)
    stats = breadth(snapshot)
    local = datetime.fromisoformat(snapshot['generated_at']).astimezone(ZoneInfo('Europe/Istanbul'))
    return ('نبض امروز کریپتو | صرافی کیانی\n\n'
            f"از {stats['total']} ارز بررسی‌شده: {stats['up']} صعودی، {stats['down']} نزولی، {stats['flat']} بدون تغییر.\n"
            + (f"برای {stats['missing']} ارز، داده تغییر ۲۴ ساعته در دسترس نیست.\n" if stats['missing'] else '') +
            '\nچهار اسلاید: نمای بازار، پیشتازان، بیشترین افت‌ها و نظر شما.\n'
            'سبدت امروز سبز بود یا قرمز؟ توی کامنت بنویس.\n\n'
            'نمای بازار: ۵۰ ارز برتر از نظر ارزش بازار، بدون استیبل‌کوین و توکن‌های رپد و استیک‌شده.\n'
            'پیشتازان و افت‌ها: حداکثر ۵ ارز با بیش از ۲٪ تغییر در قیمت دلاری ۲۴ ساعته، از میان ۱۰۰ ارز اول از نظر ارزش بازار پیش از حذف موارد نامناسب.\n'
            'فقط داده تازه و حجم معاملات ۲۴ ساعته بالاتر از ۵۰ هزار دلار؛ بدون استیبل‌کوین و توکن‌های رپد و استیک‌شده. '
            'اگر کمتر از ۵ ارز واجد شرایط باشد، فقط همان‌ها نمایش داده می‌شوند.\n\n'
            f'{local:%Y/%m/%d · %H:%M} استانبول\n'
            'منبع داده: CoinPaprika\nhttps://coinpaprika.com\n\n'
            'برای نرخ‌های لحظه‌ای ارز، ربات تلگرام کیانی:\nhttps://t.me/kianiexchangebot\n\n'
            'اطلاعات بازار برای اطلاع‌رسانی است.\nkiani.exchange')

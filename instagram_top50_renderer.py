"""Kiani gainers cover followed by five ten-coin USD/market-Toman price cards."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import io
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen
import uuid
from zoneinfo import ZoneInfo

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from crypto_top50_data import PricesError, validate_snapshot, select_decliners, timestamp

INK, MUTED, GREEN, RED = '#173D32', '#70857D', '#1C8C67', '#D9362C'
BACKGROUND, STRIPE = '#EDF4EF', '#E5EFE8'
DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
NAMES = {
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

# Only mapped identities use these icons: ticker collisions never select an icon.
ICON_NAMES = {
    'btc-bitcoin': 'btc', 'eth-ethereum': 'eth', 'bnb-binance-coin': 'bnb', 'xrp-xrp': 'xrp',
    'sol-solana': 'sol', 'trx-tron': 'trx', 'zec-zcash': 'zec', 'doge-dogecoin': 'doge',
    'xmr-monero': 'xmr', 'link-chainlink': 'link', 'ada-cardano': 'ada', 'leo-leo-token': 'leo',
    'xlm-stellar': 'xlm', 'near-near-protocol': 'near', 'bch-bitcoin-cash': 'bch',
    'ltc-litecoin': 'ltc', 'uni-uniswap': 'uni', 'avax-avalanche': 'avax',
    'hbar-hedera-hashgraph': 'hbar', 'cro-cryptocom-chain': 'cro', 'qnt-quant': 'qnt',
    'aave-new': 'aave', 'icp-internet-computer': 'icp', 'etc-ethereum-classic': 'etc',
    'ftm-fantom': 'ftm', 'algo-algorand': 'algo', 'fil-filecoin': 'fil', 'atom-cosmos': 'atom',
}
ICON_REVISION = '1a63530be6e374711a8554f31b17e4cb92c25fa5'
ICON_BASE = 'https://raw.githubusercontent.com/spothq/cryptocurrency-icons/' + ICON_REVISION + '/128/color/'


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


def coin_icon(identity, cache):
    name = ICON_NAMES.get(identity)
    if not name:
        return None
    saved = cache / (identity + '.png')
    try:
        if saved.is_file():
            data = saved.read_bytes()
        else:
            request = Request(ICON_BASE + name + '.png', headers={'User-Agent': 'KianiExchange-InstagramPrices/1.0'})
            with urlopen(request, timeout=5) as response:
                data = response.read(200_001)
            if len(data) > 200_000:
                return None
        with Image.open(io.BytesIO(data)) as source:
            if source.width > 512 or source.height > 512:
                return None
            icon = source.convert('RGBA').resize((46, 46), Image.Resampling.LANCZOS)
        if not saved.is_file():
            saved.write_bytes(data)
        return icon
    except Exception:
        return None


def significant_gainers(snapshot):
    return [c for c in snapshot['gainers']
            if Decimal(c['change_24h']).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) > 2][:5]


def summary_slides(snapshot, mode, draw, text):
    """Draw overview and losses directly from the validated market snapshot."""
    def t(value, xy, size, **kw):
        text(draw, value, xy, size, **kw)
    def box(rect, fill, radius=26):
        draw.rounded_rectangle(rect, radius=radius, fill=fill)
    def move(value):
        if value is None:
            return '—', MUTED
        value = Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        return (f'{value:+.2f}%' if value else '0.00%'), GREEN if value > 0 else RED if value < 0 else MUTED
    def names(coin):
        return NAMES.get(coin['id'], coin['name'])
    if mode == 'pulse':
        t('نبض امروز کریپتو', (1010, 225), 59, fa=True, bold=True, anchor='rm', width=940)
        t('بازار سبزه یا قرمز؟', (1010, 292), 47, fa=True, bold=True, anchor='rm', width=940)
        t('نگاهی به تغییرات ۲۴ ساعت گذشته', (1010, 344), 26, fa=True, fill=MUTED, anchor='rm')
        changes = [Decimal(c['change_24h']) for c in snapshot['coins'] if c.get('change_24h') is not None]
        up = sum(x > 0 for x in changes)
        down = sum(x < 0 for x in changes)
        flat = len(changes) - up - down
        box((58, 379, 1022, 616), INK)
        if changes:
            t(f'از {len(changes)} ارز بررسی‌شده، {up} ارز رشد کردند', (979, 427), 33,
              fa=True, bold=True, fill='white', anchor='rm', width=870)
            t(f'{(Decimal(up)*100/len(changes)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)}٪',
              (978, 503), 68, fa=True, bold=True, fill='#A9E8C5', anchor='rm')
            t('از ارزهای دارای داده', (760, 503), 26, fa=True, fill='white', anchor='rm')
            box((104, 548, 976, 566), '#D8E7DE', 9)
            width = round(872*up/len(changes))
            if width:
                draw.rectangle((976-width, 548, 976, 566), fill='#84D7A6')
            width2 = round(872*down/len(changes))
            if width2:
                draw.rectangle((976-width-width2, 548, 976-width, 566), fill='#E58F80')
            t(f'{up} صعودی', (974, 590), 22, fa=True, bold=True, fill='#B2E8C8', anchor='rm')
            t(f'{down} نزولی', (500, 590), 22, fa=True, bold=True, fill='#F4C4B9')
            t(f'{flat} بدون تغییر', (106, 590), 22, fa=True, bold=True, fill='white', anchor='lm')
        else:
            t('تغییرات ۲۴ ساعته در دسترس نیست', (540, 495), 34, fa=True, fill='white', width=820)
        for x, identity, label, symbol in ((550, 'btc-bitcoin', 'بیت‌کوین', 'BTC'), (58, 'eth-ethereum', 'اتریوم', 'ETH')):
            coin = next((c for c in snapshot['coins'] if c['id'] == identity), None)
            val, color = move(coin.get('change_24h') if coin else None)
            box((x, 637, x+472, 763), 'white')
            t(label, (x+442, 674), 28, fa=True, bold=True, anchor='rm')
            t(symbol, (x+442, 724), 22, fill=MUTED, anchor='rm')
            t(val, (x+30, 706), 36, bold=True, fill=color, anchor='lm', width=235)
        box((58, 784, 1022, 1165), 'white')
        t('پیشتازهای امروز', (978, 823), 38, fa=True, bold=True, anchor='rm')
        t('بیش از ۲٪ رشد · از میان ۱۰۰ ارز برتر', (978, 865), 23, fa=True, fill=MUTED, anchor='rm')
        rows = significant_gainers(snapshot)
        color = GREEN
        start, step = 914, 47
    else:
        t('سمت دیگر بازار', (1010, 225), 59, fa=True, bold=True, anchor='rm', width=940)
        t('کدام ارزها بیشتر افت کردند؟', (1010, 292), 42, fa=True, bold=True, anchor='rm', width=940)
        t('تغییرات قیمت دلاری در ۲۴ ساعت گذشته', (1010, 348), 26, fa=True, fill=MUTED, anchor='rm')
        box((58, 400, 1022, 1060), 'white')
        t('بیشترین افت‌های امروز', (978, 461), 42, fa=True, bold=True, anchor='rm')
        t('بیش از ۲٪ کاهش · از میان ۱۰۰ ارز برتر', (978, 515), 25, fa=True, fill=MUTED, anchor='rm')
        classes = snapshot['gainers_classifications']
        rows = select_decliners(snapshot['gainers_candidates'], set(classes['stablecoin']),
                                set(classes['wrapped_token']), timestamp(snapshot['generated_at']),
                                sample=bool(snapshot.get('sample')))
        color = RED
        start, step = 610, 79
    for i, coin in enumerate(rows):
        y = start + i*step
        if i:
            draw.line((100, y-step//2, 978, y-step//2), fill='#E5EEE8', width=1)
        t(coin['symbol'], (965, y), 24, bold=True, fill=MUTED, anchor='rm', width=135)
        t(names(coin), (805, y), 25, fa=coin['id'] in NAMES, bold=True, anchor='rm', width=430)
        t(move(coin['change_24h'])[0], (116, y), 29, bold=True, fill=color, anchor='lm', width=200)
    if len(rows) < 5:
        message = 'ارز دیگری با این شرایط یافت نشد' if rows else 'ارز واجد شرایطی با این میزان تغییر یافت نشد'
        y = min((1140 if mode == 'pulse' else 1020), start + len(rows)*step + 22)
        t(message, (540, y), 25, fa=True, fill=MUTED, width=850)
    t('برای ادامه ورق بزنید', (540, 1220), 30, fa=True, bold=True, fill=GREEN)
    t('CoinPaprika · تغییرات ۲۴ ساعته', (540, 1265), 23, fa=True, fill=MUTED)


def render(snapshot, output, asset_root):
    validate_snapshot(snapshot)
    output, asset_root = Path(output).resolve(), Path(asset_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = output / '.coin-icons' / ICON_REVISION
    cache.mkdir(parents=True, exist_ok=True)
    fonts = {}

    def font(size, bold=False):
        key = (size, bold)
        if key not in fonts:
            name = 'Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf'
            fonts[key] = ImageFont.truetype(str(asset_root / 'fonts' / name), size,
                                           layout_engine=ImageFont.Layout.BASIC)
        return fonts[key]

    def rtl(text):
        return get_display(arabic_reshaper.reshape(str(text).translate(DIGITS)), base_dir='R')

    def text(draw, value, xy, size, *, fa=False, bold=False, fill=INK, anchor='mm', width=None):
        value = rtl(value) if fa else str(value)
        while width and draw.textlength(value, font=font(size, bold)) > width and size > 16:
            size -= 1
        if width and draw.textlength(value, font=font(size, bold)) > width:
            raise PricesError('A table label or price is too wide to render safely.')
        draw.text(xy, value, font=font(size, bold), fill=fill, anchor=anchor)

    logo_source = ET.parse(asset_root / 'assets/instagram/kiani-logo.svg').getroot()
    _, _, lw, lh = map(float, logo_source.attrib['viewBox'].split())
    logo = Image.new('RGBA', (256, 256))
    for node in logo_source.iter('{http://www.w3.org/2000/svg}polygon'):
        points = [tuple(map(float, pair.split(','))) for pair in node.attrib['points'].split()]
        ImageDraw.Draw(logo).polygon([(x * 256/lw, y * 256/lh) for x, y in points], fill=INK)
    logo = logo.resize((40, 41), Image.Resampling.LANCZOS)
    all_coins = {c['id']: c for c in [*snapshot.get('gainers', []), *snapshot['coins']]}
    with ThreadPoolExecutor(max_workers=6) as pool:
        icons = dict(zip(all_coins, pool.map(lambda c: coin_icon(c['id'], cache), all_coins.values())))
    local = datetime.fromisoformat(snapshot['generated_at']).astimezone(ZoneInfo('Europe/Istanbul'))
    stamp = f'{local:%Y/%m/%d · %H:%M} استانبول'
    prefix = f"kiani-top50-{local:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:10]}"
    paths = []
    sections = [('prices', page, snapshot['coins'][(page-1)*10:page*10]) for page in range(1, 6)]
    if snapshot.get('schema') == 3:
        sections[0:0] = [('pulse', 0, []), ('declines', 0, [])]
    total = len(sections)
    for page, (mode, price_page, rows) in enumerate(sections, 1):
        is_gainers = False
        image = Image.new('RGB', (1080, 1350), BACKGROUND)
        draw = ImageDraw.Draw(image)
        if snapshot.get('sample'):
            draw.rectangle((0, 0, 1080, 53), fill='#A87020')
            text(draw, 'نمونه برای بررسی طرح · نرخ لحظه‌ای نیست', (540, 27), 26,
                 fa=True, bold=True, fill='white')
        draw.rounded_rectangle((64, 76, 1016, 88), radius=6, fill='#D5E4DA')
        draw.rounded_rectangle((1016 - round(952*page/total), 76, 1016, 88), radius=6, fill=GREEN)
        image.paste(logo, (976, 119), logo)
        text(draw, 'صرافی کیانی', (964, 142), 31, fa=True, bold=True, anchor='rm', width=230)
        text(draw, 'kiani.exchange', (64, 142), 33, bold=True, anchor='lm')
        if mode in {'pulse', 'declines'}:
            summary_slides(snapshot, mode, draw, text)
            text(draw, stamp, (540, 1307), 22, fa=True, fill=MUTED, width=850)
            text(draw, f'{page} / {total}', (64, 1307), 25, anchor='lm', fill=MUTED)
            path = output / f'{prefix}-{page:02}.jpg'
            image.save(path, 'JPEG', quality=95, subsampling=0, optimize=True)
            paths.append(path)
            continue
        title = ('۱۰ ارز با بیشترین رشد' if len(rows) == 10 else f'{len(rows)} ارز با رشد مثبت') if is_gainers else '۵۰ ارز دیجیتال برتر'
        if is_gainers and not rows:
            title = 'رشد ارزها در ۲۴ ساعت'
        text(draw, title, (540, 232), 64, fa=True, bold=True, width=952)
        subtitle = ('۲۴ ساعت گذشته · از میان ۱۰۰ ارز برتر بازار' if is_gainers else
                    f'قیمت به دلار و تومان · بدون استیبل‌کوین · بخش {price_page} از 5')
        text(draw, subtitle,
             (540, 297), 27, fa=True, fill=MUTED, width=952)
        draw.rounded_rectangle((320, 326, 760, 370), radius=21, fill='#DDEBE2')
        text(draw, 'هر تتر = ' + price_text(snapshot['usdt_toman']) + ' تومان',
             (540, 348), 26, fa=True, bold=True, width=412)
        for label, x in (('۲۴ ساعت', 145), ('دلار', 311), ('تومان', 537), ('ارز', 805), ('#', 976)):
            text(draw, label, (x, 400), 25, fa=True, bold=True, fill=MUTED)
        row_step = min(138, 592 / max(1, len(rows) - 1)) if is_gainers and len(rows) < 9 else 74
        half_height = min(52, row_step / 2 - 7) if is_gainers else 33
        first_y = 480 if is_gainers else 461
        for index, coin in enumerate(rows):
            y = round(first_y + index*row_step)
            draw.rounded_rectangle((64, y-half_height, 1016, y+half_height), radius=16,
                                   fill=('#D5E9DA' if index < 3 else 'white') if is_gainers else
                                        ('white' if index % 2 == 0 else STRIPE))
            text(draw, coin['position'], (977, y), 25, bold=True,
                 fill=GREEN if is_gainers else MUTED, width=48)
            icon = icons[coin['id']]
            if icon is not None:
                image.paste(icon, (899, y-23), icon)
            else:
                colors = ('#2E665B', '#317FAD', '#876FCA', '#D18A29', '#479B80')
                shade = colors[int(hashlib.sha256(coin['id'].encode()).hexdigest(), 16) % len(colors)]
                draw.ellipse((899, y-23, 945, y+23), fill=shade)
                text(draw, coin['symbol'][:2], (922, y), 20, bold=True, fill='white', width=38)
            text(draw, coin['symbol'], (879, y-12), 29, bold=True, fill=GREEN, anchor='rm', width=201)
            name = NAMES.get(coin['id'], coin['name'])
            text(draw, name, (879, y+19), 20, fa=coin['id'] in NAMES,
                 anchor='rm', fill=MUTED, width=201)
            text(draw, price_text(coin['toman']), (537, y), 30, bold=True, width=253)
            text(draw, price_text(coin['usd'], usd=True), (311, y), 28, width=178)
            if coin['change_24h'] is None:
                change, color, direction = '—', MUTED, 0
            else:
                value = Decimal(coin['change_24h'])
                shown = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                color = GREEN if shown > 0 else RED if shown < 0 else MUTED
                direction = 1 if shown > 0 else -1 if shown < 0 else 0
                change = f'{shown:+.2f}%'
                if shown == 0:
                    change = '0.00%'
            if direction:
                points = [(84, y-7), (77, y+6), (91, y+6)] if direction > 0 else [(77, y-6), (91, y-6), (84, y+7)]
                draw.polygon(points, fill=color)
            elif coin['change_24h'] is not None:
                draw.ellipse((81, y-3, 87, y+3), fill=MUTED)
            text(draw, change, (158, y), 24, fill=color, width=112)
            if is_gainers and half_height >= 45:
                width = float(Decimal(coin['change_24h']) / Decimal(rows[0]['change_24h'])) * 545
                draw.rounded_rectangle((100, y+32, 100+max(3, width), y+37), radius=2, fill=GREEN)
        if is_gainers and len(rows) < 10:
            message = ('هیچ ارز واجد شرایطی رشد مثبت نداشت' if not rows else
                       'امروز کمتر از ۱۰ ارز واجد شرایط رشد مثبت داشتند')
            message_y = max(620, min(1140, first_y + max(0, len(rows)-1)*row_step + half_height + 52))
            text(draw, message, (540, message_y), 30,
                 fa=True, bold=True, fill=MUTED, width=920)
        draw.line((64, 1195, 1016, 1195), fill='#D5E4DA', width=2)
        note = ('حجم ۲۴ساعته بالای ۵۰ هزار دلار · منبع: CoinPaprika' if is_gainers else
                'نرخ‌ها صرفاً جهت اطلاع‌رسانی است · منبع: CoinPaprika')
        text(draw, note,
             (540, 1224), 23, fa=True, fill=MUTED, width=952)
        text(draw, stamp,
             (540, 1263 if page < total else 1255), 24, fa=True, fill=MUTED, width=952)
        text(draw, f'{page} / {total}', (64, 1308), 25, anchor='lm', fill=MUTED)
        if page < total:
            text(draw, 'برای قیمت ۵۰ ارز ورق بزنید' if is_gainers else 'صرافی کیانی · ورق بزنید',
                 (540, 1308), 28, fa=True, bold=True, fill=GREEN)
        else:
            text(draw, 'ربات نرخ لحظه‌ای در تلگرام', (540, 1284), 23, fa=True, fill=GREEN)
            text(draw, 'Telegram · https://t.me/kianiexchangebot', (590, 1320), 25,
                 bold=True, fill=GREEN, width=814)
        path = output / f'{prefix}-{page:02}.jpg'
        image.save(path, 'JPEG', quality=95, subsampling=0, optimize=True)
        paths.append(path)
    return paths


def caption(snapshot):
    local = datetime.fromisoformat(snapshot['generated_at']).astimezone(ZoneInfo('Europe/Istanbul'))
    intro = ('صرافی کیانی | نبض بازار و قیمت ۵۰ ارز دیجیتال\n\n'
             '۷ اسلاید: نمای بازار، بیشترین افت‌ها و سپس قیمت ۵۰ ارز در ۵ اسلاید.\n'
             'نمای بازار بر اساس ارزهای دارای تغییر ۲۴ ساعته در فهرست ۵۰ ارز است.\n'
             'حداکثر ۵ رشد و ۵ افت بیش از ۲٪ بر اساس تغییر قیمت دلاری ۲۴ ساعت، میان ۱۰۰ ارز اول از نظر ارزش بازار پیش از حذف استیبل‌کوین‌ها.\n'
             'فقط داده تازه و حجم معاملات ۲۴ساعته بالاتر از ۵۰ هزار دلار؛ بدون استیبل‌کوین و نسخه‌های رپد و استیک‌شده.\n'
             'اگر تعداد ارزهای واجد شرایط کمتر از ۵ باشد، فقط همان‌ها نمایش داده می‌شوند.\n\n'
             if snapshot.get('schema') == 3 else 'صرافی کیانی | قیمت ۵۰ ارز دیجیتال برتر\n\n۵ اسلاید؛ قیمت به دلار و تومان و تغییر ۲۴ ساعته قیمت دلاری.\n')
    return (intro +
            'فهرست ۵۰ ارز بر اساس ارزش بازار، بدون استیبل‌کوین و نسخه‌های رپد و استیک‌شده.\n\n'
            'قیمت تومان = قیمت دلاری هر ارز × نرخ بازار تتر\n'
            f"هر تتر = {price_text(snapshot['usdt_toman'])} تومان\n"
            f"نرخ تتر: {snapshot.get('rate_caption_fa', 'آخرین معامله بازار USDTTMN در والکس')}.\n"
            'نرخ بازار تتر به نزدیک‌ترین ۱۰۰ تومان گرد شده است.\n'
            'محاسبه با قیمت دلاری کامل منبع انجام می‌شود؛ اعداد روی تصویر گرد شده‌اند.\n\n'
            f'{local:%Y/%m/%d · %H:%M} استانبول\n'
            'منبع قیمت دلاری و ارزش بازار: CoinPaprika\n'
            'https://coinpaprika.com\n'
            f"منبع نرخ بازار تتر: {snapshot.get('rate_public_url', 'https://wallex.ir')}\n\n"
            'نرخ‌ها صرفاً جهت اطلاع‌رسانی است.\n'
            'ربات تلگرام نرخ لحظه‌ای: @kianiexchangebot\n'
            'https://t.me/kianiexchangebot\n\n'
            'kiani.exchange')

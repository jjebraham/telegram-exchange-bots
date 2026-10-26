"""Four reference-driven report layouts; consumes approved publisher text only.

No fetching, price conversion, midpoint calculation, or history calculation is
performed here. Period labels follow producer contracts, never sample artwork.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape, unescape
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from market_images import (CURRENCY_NAMES, GOLD_TR, PCT, RATE, PERSIAN_DIGITS,
                           _pre, _fa_num, _usdt_percent, _asset_data, _font_css,
                           _jalali, USDT_CLOCK, USDT_CAL, USDT_HEADER_DECOR)

CURRENCY_FLAG_CODES = dict(zip(
    'USD EUR GBP CHF CAD AUD SEK NOK RUB THB SGD HKD AZN DKK AED TRY CNY SAR INR MYR AFN KWD BHD OMR QAR'.split(),
    'us eu gb ch ca au se no ru th sg hk az dk ae tr cn sa in my af kw bh om qa'.split()))
CURRENCY_ORDER = tuple(CURRENCY_FLAG_CODES)
GOLD_COINS = ('سکه امامی', 'سکه بهار آزادی', 'نیم سکه', 'ربع سکه', 'سکه گرمی')
GOLD_BARS = ('طلای ۱۸ عیار', 'مثقال طلا')
ARTBOARDS = {'iran-fx': (1200, 1500), 'iran-gold': (1200, 1200),
             'turkey-gold': (1200, 1200), 'fx-pulse': (1200, 1200)}


def flag_emoji(code: str) -> str:
    return ''.join(chr(127397 + ord(char)) for char in CURRENCY_FLAG_CODES[code].upper())


def flag_html(code: str) -> str:
    country = CURRENCY_FLAG_CODES[code]
    return (f'<img class="currency-flag" data-flag="{country}" '
            f'src="{_asset_data("flags/" + country + ".svg")}" alt="{country.upper()}">')


@dataclass(frozen=True)
class FxRow:
    code: str
    price: str
    day: str
    month: str


@dataclass(frozen=True)
class GoldRow:
    name: str
    price: str
    day: str
    month: str = '—'


@dataclass(frozen=True)
class TurkishGoldRow:
    code: str
    sell: str
    buy: str
    day: str
    month: str = '—'


@dataclass(frozen=True)
class PulseRow:
    pair: str
    rate: str
    day: str
    month: str = '—'


def _table_has_month(text: str, columns: tuple[str, ...]) -> bool:
    """Accept only the declared legacy daily or extended daily/monthly schema."""
    match = re.search(r'<pre>(.*?)</pre>',text,re.S)
    if not match:
        raise ValueError('Missing approved preformatted market table')
    first = unescape(match.group(1)).splitlines()[0].lstrip('\u200e🌕 ')
    header = tuple(first.split())
    if header == columns:
        return False
    if header == columns + ('Δ1M',):
        return True
    raise ValueError('Unrecognized market-period columns')


def parse_iran_fx(text: str) -> list[FxRow]:
    pattern = re.compile(rf'^\S+\s+([A-Z]{{3}})\s+({RATE})\s+({PCT})\s+({PCT})$')
    rows = {}
    for line in _pre(text):
        match = pattern.fullmatch(line)
        if not match:
            raise ValueError('Malformed Iran FX row')
        code, price, day, month = match.groups()
        if code not in CURRENCY_NAMES or code in rows:
            raise ValueError('Unknown or repeated currency: ' + code)
        rows[code] = FxRow(code, price, day, month)
    if set(rows) != set(CURRENCY_ORDER):
        raise ValueError('Iran FX requires all 25 currency slots, with dashes for unavailable data')
    return [rows[code] for code in CURRENCY_ORDER]


def parse_iran_gold(text: str) -> list[GoldRow]:
    visible = unescape(re.sub(r'<[^>]*>',' ',text))
    monthly = bool(re.search(r'Δ24H\s*/\s*Δ1M',visible))
    if 'Δ1M' in visible and not monthly:
        raise ValueError('Unrecognized Iranian gold period columns')
    pattern = re.compile(rf'^[^<]*<b>([^<]+)</b>\s*<code>({RATE})</code>\s*({PCT})(?:\s*/\s*({PCT}))?\s*$')
    rows = {}
    for line in text.splitlines():
        if '<b>' not in line or '<code>' not in line:
            continue
        match = pattern.fullmatch(line)
        if not match:
            raise ValueError('Malformed Iran gold row')
        name, price, day, month = match.groups()
        if monthly != (month is not None):
            raise ValueError('Iranian gold row does not match its declared periods')
        if name not in GOLD_COINS + GOLD_BARS or name in rows:
            raise ValueError('Unknown or repeated gold instrument')
        rows[name] = GoldRow(name, price, day, month if monthly else '—')
    if not set(GOLD_COINS) <= set(rows):
        raise ValueError('Missing Iranian coin rows')
    return [rows[name] for name in GOLD_COINS + GOLD_BARS if name in rows]


def parse_turkey_gold(text: str) -> list[TurkishGoldRow]:
    rows = {}
    monthly = _table_has_month(text,('GOLD','SELL','BUY','Δ24H'))
    suffix = rf'\s+({PCT})' if monthly else ''
    pattern = re.compile(rf'^(\S+)\s+({RATE})\s+({RATE})\s+({PCT}){suffix}$')
    for line in _pre(text):
        match = pattern.fullmatch(line.removeprefix('🌕'))
        if not match:
            raise ValueError('Malformed Turkish gold row')
        fields = match.groups()
        code, sell, buy, day = fields[:4]
        if code not in GOLD_TR or code in rows:
            raise ValueError('Unknown or repeated Turkish gold instrument')
        rows[code] = TurkishGoldRow(code, sell, buy, day, fields[4] if monthly else '—')
    if set(rows) != set(GOLD_TR):
        raise ValueError('Missing Turkish gold instruments')
    return [rows[code] for code in GOLD_TR]


def parse_pulse(text: str) -> list[PulseRow]:
    rows = {}
    monthly = _table_has_month(text,('MARKET','RATE','Δ24H'))
    suffix = rf'\s+({PCT})' if monthly else ''
    pattern = re.compile(rf'^[^\w\s<]*(USD/TL|EUR/TL)\s+(\d+\.\d{{4}}|—)\s+({PCT}){suffix}$')
    for line in _pre(text):
        match = pattern.fullmatch(line)
        if not match:
            raise ValueError('Malformed Turkey FX pulse row')
        fields = match.groups()
        pair, rate, day = fields[:3]
        if pair in rows:
            raise ValueError('Repeated FX pulse market')
        rows[pair] = PulseRow(pair, rate, day, fields[3] if monthly else '—')
    if set(rows) != {'USD/TL', 'EUR/TL'}:
        raise ValueError('Missing USD/TL or EUR/TL market')
    return [rows[pair] for pair in ('USD/TL', 'EUR/TL')]


def number(raw: str, style: str = 'price') -> str:
    return f'<span class="num {style}" dir="ltr" data-value="{escape(raw)}">{_fa_num(raw, percent=True)}</span>'


def change(raw: str, period: str) -> str:
    return f'<span class="period" data-period="{period}" data-value="{escape(raw)}">{_usdt_percent(raw)}</span>'


def heads(labels: tuple[str, ...]) -> str:
    return '<thead><tr>' + ''.join(f'<th>{escape(label)}</th>' for label in labels) + '</tr></thead>'


def gold_art(variant: str) -> str:
    if variant.startswith('bar'):
        return (f'<svg class="gold-art {variant}" viewBox="0 0 76 54" aria-hidden="true">'
                '<defs><linearGradient id="bar-face"><stop stop-color="#fff2a3"/><stop offset="1" stop-color="#e6aa0b"/></linearGradient></defs>'
                '<path d="M12 14L59 10 71 35 4 40Z" fill="url(#bar-face)" stroke="#d79a03" stroke-width="2.5"/>'
                '<path d="M12 14L4 40H63L59 10M63 40l8-5-12-25" fill="#e2a508" stroke="#c48b00" stroke-width="2"/>'
                '<path d="M12 14h44l7 26H4Z" fill="url(#bar-face)"/>'
                '<path d="M14 16h39" stroke="#fff6c3" stroke-width="3"/></svg>')
    return (f'<svg class="gold-art coin-{variant}" viewBox="0 0 68 68" aria-hidden="true">'
            '<defs><radialGradient id="coin-face" cx=".28" cy=".2" r=".9"><stop stop-color="#ffe998"/><stop offset=".65" stop-color="#edc33d"/><stop offset="1" stop-color="#d5a119"/></radialGradient>'
            '<linearGradient id="coin-edge"><stop stop-color="#b47d00"/><stop offset=".45" stop-color="#ffdf6c"/><stop offset="1" stop-color="#c88c05"/></linearGradient></defs>'
            '<circle cx="34" cy="34" r="31" fill="url(#coin-edge)" stroke="#c78f05" stroke-width="2"/>'
            '<circle cx="34" cy="34" r="26.5" fill="url(#coin-face)" stroke="#ffe790" stroke-width="2"/>'
            '<path d="M13 31a23 23 0 0 1 30-19" fill="none" stroke="#fff2bd" stroke-width="2.5" stroke-linecap="round"/>'
            '<path d="M55 39a23 23 0 0 1-26 18" fill="none" stroke="#b78006" stroke-opacity=".4" stroke-width="2"/></svg>')


WATERMARK = '''<svg class="brand-watermark" viewBox="0 0 600 600" aria-hidden="true"><circle cx="300" cy="300" r="260" fill="none" stroke="currentColor" stroke-width="38"/><path d="M145 440L285 130h30l140 310h-54l-42-94H240l-42 94zm115-140h80l-40-93z" fill="currentColor"/></svg>'''


def iran_fx_body(text: str) -> str:
    rows = parse_iran_fx(text)
    def half(chunk: list[FxRow], unit: bool = False) -> str:
        table_rows = []
        for row in chunk:
            label = (f'<div class="currency-name">{flag_html(row.code)}<div class="name-stack">'
                     f'<strong>{escape(CURRENCY_NAMES[row.code])}</strong><small>{row.code}</small></div></div>')
            table_rows.append(f'<tr data-code="{row.code}"><td>{label}</td><td>{number(row.price)}</td></tr>')
        table = '<table class="fx-table"><tbody>' + ''.join(table_rows) + '</tbody></table>'
        if unit:
            missing = [row.code for row in rows if row.price == '—']
            note = ('<small class="availability-note">نرخ ناموجود: ' + '، '.join(missing) + '</small>') if missing else ''
            table += '<div class="fx-unit">واحد: <b>تومان</b>' + note + '</div>'
        return '<div class="fx-half">' + table + '</div>'
    return '<div class="fx-board">' + half(rows[:13]) + half(rows[13:],True) + '</div>'


def iran_gold_body(text: str) -> str:
    rows = parse_iran_gold(text)
    table = '<table class="gold-table iran-gold-table">' + heads(('نوع','قیمت بازار','۲۴ ساعت','۱ ماه')) + '<tbody>'
    for group, label in ((GOLD_COINS,'سکه'),(GOLD_BARS,'طلا')):
        selected = [row for row in rows if row.name in group]
        if not selected:
            continue
        table += f'<tr class="section-heading"><td colspan="4"><div><b>{label}</b><i></i></div></td></tr>'
        for row in selected:
            variant = {GOLD_COINS[0]:'full',GOLD_COINS[1]:'full',GOLD_COINS[2]:'half',GOLD_COINS[3]:'quarter',GOLD_COINS[4]:'small',GOLD_BARS[0]:'bar',GOLD_BARS[1]:'bar-mesghal'}[row.name]
            table += (f'<tr class="instrument-row" data-instrument="{escape(row.name)}"><td>'
                      f'<div class="instrument-name">{gold_art(variant)}<strong>{escape(row.name)}</strong></div></td>'
                      f'<td>{number(row.price)}</td><td>{change(row.day,"24h")}</td><td>{change(row.month,"1m")}</td></tr>')
    return table + '</tbody></table>'


def turkey_gold_body(text: str) -> str:
    table = '<table class="gold-table turkey-gold-table">' + heads(('نوع طلا','فروش','خرید','۲۴ ساعت','۱ ماه')) + '<tbody>'
    for row in parse_turkey_gold(text):
        name, latin = GOLD_TR[row.code]
        variant = {'GRAM':'bar','CEYREK':'quarter','YARIM':'half','TAM':'full'}[row.code]
        table += (f'<tr class="instrument-row" data-instrument="{row.code}"><td>'
                  f'<div class="instrument-name">{gold_art(variant)}<div class="name-stack"><strong>{escape(name)}</strong><small>{escape(latin)}</small></div></div></td>'
                  f'<td>{number(row.sell,"sell")}</td><td>{number(row.buy,"buy")}</td>'
                  f'<td>{change(row.day,"24h")}</td><td>{change(row.month,"1m")}</td></tr>')
    return table + '</tbody></table>' + currency_unit()


def currency_unit() -> str:
    return '<div class="currency-unit"><span>واحد: <b>لیر ترکیه</b></span>' + flag_html('TRY') + '</div>'


def pulse_body(text: str) -> str:
    cards = []
    for row in parse_pulse(text):
        code = row.pair[:3]
        label = 'دلار آمریکا به لیر' if code == 'USD' else 'یورو به لیر'
        cards.append(
            f'<section class="pulse-card" data-pair="{row.pair}"><div class="pair-identity">'
            f'<div class="pair-flags">{flag_html(code)}{flag_html("TRY")}</div>'
            f'<h2 dir="ltr">{code} / TL</h2><p>{label}</p></div>'
            f'<div class="rate-block">{number(row.rate,"pulse-rate")}<small>لیر ترکیه</small></div>'
            '<div class="movement-panels">'
            f'<div class="movement"><span>۲۴ ساعت</span>{change(row.day,"24h")}</div>'
            f'<div class="movement"><span>۱ ماه</span>{change(row.month,"1m")}</div>'
            '</div></section>')
    return '<div class="pulse-cards">' + ''.join(cards) + '</div>' + currency_unit()


def render_report(kind: str, text: str, now: datetime | None = None) -> str:
    zone = ZoneInfo('Asia/Tehran' if kind.startswith('iran-') else 'Europe/Istanbul')
    if now is not None and now.tzinfo is None:
        raise ValueError('An explicit rendering timestamp must include its timezone')
    explicit = now is not None
    now = now.astimezone(zone) if explicit else datetime.now(zone)
    city = 'تهران' if kind.startswith('iran-') else 'استانبول'
    clock = re.search(rf'🕒\s*<code>((?:[01]\d|2[0-3]):[0-5]\d)</code>\s*{city}', text)
    time = (now.strftime('%H:%M') if explicit else clock.group(1) if clock else '—').translate(PERSIAN_DIGITS)
    date = _jalali(now).translate(PERSIAN_DIGITS)
    titles = {'iran-fx':'نرخ ارز آزاد ایران','iran-gold':'طلا و سکه ایران',
              'turkey-gold':'قیمت طلای ترکیه','fx-pulse':'نبض بازار ارز ترکیه'}
    subtitles = {'iran-fx':'ارقام به تومان','iran-gold':'قیمت بازار · ارقام به تومان',
                 'turkey-gold':'بازار <bdi>Kapalıçarşı</bdi>','fx-pulse':'نرخ میانی دلار و یورو · <bdi>Kapalıçarşı</bdi>'}
    header_art = USDT_HEADER_DECOR if kind == 'iran-fx' else ''
    calendar = USDT_CAL if kind == 'iran-fx' else ''
    clock_icon = USDT_CLOCK if kind == 'iran-fx' else ''
    header = (f'<header class="report-header">{header_art}<div class="report-date">{calendar}<span>{date}</span></div>'
              f'<div class="report-clock">{clock_icon}<span class="clock-value num" dir="ltr">{time}</span><small>{city}</small></div></header>')
    if kind == 'turkey-gold':
        secondary = '<div class="buy-sell-key"><span>فروش <bdi>SELL</bdi></span><span>خرید <bdi>BUY</bdi></span></div>'
    elif kind == 'fx-pulse':
        secondary = '<div class="pulse-period">24H</div>'
    else:
        secondary = '<div class="report-subtitle">' + subtitles[kind] + '</div>'
    subtitle = '<div class="title-subtitle">' + subtitles[kind] + '</div>' if kind in {'turkey-gold','fx-pulse'} else ''
    title = f'<section class="report-title"><div><h1>{titles[kind]}</h1>{subtitle}</div>{secondary}</section>'
    body = {'iran-fx':iran_fx_body,'iran-gold':iran_gold_body,'turkey-gold':turkey_gold_body,'fx-pulse':pulse_body}[kind](text)
    height = ARTBOARDS[kind][1]
    if kind == 'iran-gold':
        row_count = len(parse_iran_gold(text))
        height -= 92 * (7-row_count) + (60 if row_count == 5 else 0)
    footer_text = 'نرخ‌ها مربوط به بازار آزاد و صرفاً جهت اطلاع‌رسانی هستند.' if kind == 'iran-fx' else 'قیمت‌ها صرفاً جهت اطلاع‌رسانی است.'
    footer = f'<footer class="report-footer"><span>{footer_text}</span><b dir="ltr">@alanchande_com</b></footer>'
    return ('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>'
            f':root{{--height:{height}px}}' + _font_css() + REPORT_CSS
            + f'</style></head><body><div class="canvas report {kind}">{header}<div class="accent-stripe"></div>{title}'
            + f'<main class="report-main">{WATERMARK}<div class="report-content">{body}</div></main><div class="accent-stripe"></div>{footer}</div></body></html>')


def validate_report_layout(page) -> None:
    """Fit long approved text, then reject missing assets or clipped fields."""
    errors = page.evaluate('''() => {
      const innerWidth=e=>{const s=getComputedStyle(e);return e.clientWidth-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight)};
      for(const e of document.querySelectorAll('.report td .num,.report .rate-block .num,.report .movement .num')) {
        const cell=e.closest('td'), rate=e.closest('.rate-block'), movement=e.closest('.movement');
        const box=cell || rate || movement;
        let available=innerWidth(box);
        if(movement) available-=movement.firstElementChild.getBoundingClientRect().width+12;
        const width=e.getBoundingClientRect().width;
        if(width>available) e.style.fontSize=(parseFloat(getComputedStyle(e).fontSize)*available/width-.5)+'px';
      }
      for(const e of document.querySelectorAll('.currency-name strong,.instrument-name strong,.instrument-name small')) {
        const stack=e.closest('.name-stack');
        let available;
        if(stack) available=stack.clientWidth;
        else {const row=e.parentElement;available=innerWidth(row)-row.querySelector('svg').getBoundingClientRect().width-16;}
        const width=Math.max(e.scrollWidth,e.getBoundingClientRect().width);
        if(width>available) e.style.fontSize=(parseFloat(getComputedStyle(e).fontSize)*available/width-.5)+'px';
      }
      const errors=[], canvas=document.querySelector('.canvas').getBoundingClientRect();
      const selector='.report th,.report td .num,.report .name-stack,.report .instrument-name strong,.report .report-date,.report .report-clock,.report h1,.report .report-subtitle,.report .title-subtitle,.report .movement,.report .rate-block,.report .pair-identity,.report-footer,.report .currency-unit,.report .fx-unit';
      for(const e of document.querySelectorAll(selector)) {
        const r=e.getBoundingClientRect(), cell=e.closest('td'), card=e.closest('.pulse-card');
        const box=(cell||card)?.getBoundingClientRect() || canvas;
        if(r.left<box.left-1 || r.right>box.right+1 || r.top<box.top-1 || r.bottom>box.bottom+1 || e.scrollWidth>e.clientWidth+1) errors.push((e.className||e.tagName)+': '+e.innerText.slice(0,32));
      }
      const content=document.querySelector('.report-content').getBoundingClientRect();
      for(const e of document.querySelectorAll('.report-content table,.report-content .pulse-cards,.report-content .fx-unit,.report-content .currency-unit')) {
        if(e.getBoundingClientRect().bottom>content.bottom+1) errors.push('content extends below main area');
      }
      for(const i of document.images) if(!i.complete || !i.naturalWidth) errors.push('unloaded flag/artwork');
      if(!document.fonts.check('900 40px AlanVazir')) errors.push('unloaded Persian font');
      return errors;
    }''')
    if errors:
        raise RuntimeError('Report layout overflow or missing asset: ' + '; '.join(errors))


REPORT_CSS = r'''
*{box-sizing:border-box}html,body{margin:0;padding:0;background:white}
.canvas.report{width:1200px;height:var(--height);display:flex;flex-direction:column;direction:rtl;background:#fff;color:#10113c;font-family:AlanVazir,sans-serif}
.report .num{display:inline-block;white-space:nowrap;unicode-bidi:isolate;flex-shrink:0;font-weight:900;line-height:1.5}
.report-header{height:104px;flex-shrink:0;background:linear-gradient(105deg,#4243b8,#4840af 72%,#4946b7);color:#fff;display:flex;align-items:center;justify-content:space-between;padding:0 44px;position:relative;overflow:hidden}
.report-date,.report-clock{position:relative;z-index:1;display:flex;align-items:center;gap:20px;white-space:nowrap;line-height:1.6}
.report-date{font-size:40px;font-weight:800}.report-clock{direction:ltr}.clock-value{font-size:53px;color:#ffe27a;font-weight:900}.report-clock small{font-size:29px;font-weight:600}
.report-header svg{width:48px;height:48px;flex-shrink:0}.report-header .header-landscape{position:absolute;bottom:0;left:365px;width:445px;height:130px;opacity:.27}
.accent-stripe{height:12px;flex-shrink:0;background:linear-gradient(90deg,#ff7169 0 50%,#7adce6 50%)}
.report-title{height:124px;flex-shrink:0;padding:0 44px;display:flex;align-items:center;justify-content:space-between;gap:24px;border-bottom:3px solid #4940c6}
.report-title h1{margin:0;white-space:nowrap;font-size:66px;font-weight:900;line-height:1.55;background:linear-gradient(0deg,#3531ba,#584ed1);background-clip:text;color:transparent;border-right:17px solid #e6ac16;border-radius:8px;padding-right:22px;letter-spacing:-1.8px}
.report-subtitle{font-size:26px;font-weight:750;color:#4b496e;white-space:nowrap}.title-subtitle{font-size:29px;font-weight:700;color:#4b496e;margin-top:-5px;padding-right:39px}
.report-main{position:relative;flex:1;min-height:0;padding:20px 42px 24px}.report-content{position:relative;z-index:1;display:flex;flex-direction:column;height:100%}
.brand-watermark{position:absolute;width:650px;height:650px;top:50%;left:50%;transform:translate(-50%,-50%);color:#4b45bc;opacity:.035;pointer-events:none}
table{width:100%;border-collapse:separate;border-spacing:0;table-layout:fixed;direction:rtl}th,td{text-align:center;vertical-align:middle}
th{height:64px;padding:0 8px;background:#f0eff8;color:#302d58;font-size:28px;font-weight:800;white-space:nowrap}
th:first-child{border-radius:0 18px 18px 0}th:last-child{border-radius:18px 0 0 18px}
td{padding:0 9px;line-height:1.5}td:first-child,th:first-child{text-align:right;padding-right:24px}
.report .price{color:#10113c}.report .sell{color:#e0002d}.report .buy,.report .up{color:#00812e}.report .down{color:#e20030}.report .muted{color:#65618b}
.report .percentage{display:inline-flex;direction:ltr;align-items:baseline;white-space:nowrap;gap:0;font-size:35px;letter-spacing:-1.2px}.period{display:inline-block;white-space:nowrap}
.instrument-name{display:flex;align-items:center;gap:16px;font-size:33px;font-weight:850;white-space:nowrap}.name-stack{display:flex;flex-direction:column;min-width:0}.name-stack strong{font-weight:850;white-space:nowrap}.name-stack small{font:700 24px Arial,sans-serif;color:#4b476f;line-height:1.6;direction:ltr;text-align:right}
.gold-art{width:62px;height:62px;flex-shrink:0}.gold-art.coin-half{width:55px;height:55px}.gold-art.coin-quarter{width:47px;height:47px}.gold-art.coin-small{width:37px;height:37px}.gold-art.bar,.gold-art.bar-mesghal{height:48px}.gold-art.bar-mesghal{width:56px}
.gold-table th:first-child{width:32%}.gold-table th:nth-child(2){width:34%}.gold-table th:nth-child(3){width:18%}.gold-table th:nth-child(4){width:16%}
.instrument-row td{height:92px;background:#f7f8fdc4;border-bottom:1px solid #e6e5f2}.instrument-row td:first-child{border-radius:0 16px 16px 0}.instrument-row td:last-child{border-radius:16px 0 0 16px}
.instrument-row .price{font-size:60px;letter-spacing:-1px;color:#000}.section-heading td{height:60px;background:none;border:0;padding:0 20px}.section-heading td div{display:flex;align-items:center;gap:16px;color:#b77a12;font-size:31px;font-weight:900}.section-heading i{height:2px;background:#edc75b88;flex:1}
.report-footer{height:76px;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;padding:0 44px;background:linear-gradient(110deg,#4643ba,#4942b2);color:#fff;font-size:23px;font-weight:550;gap:30px}
.report-footer b{font:800 28px Arial,sans-serif;color:#ffe27a;white-space:nowrap}
.canvas.report.iran-fx{background:#f7f6fc}.iran-fx .report-header{height:128px}.iran-fx .accent-stripe{height:8px}.iran-fx .report-title{height:124px;border:0;padding:0 32px 0 42px}.iran-fx .report-title h1{font-size:68px;border-color:#fa7972}.iran-fx .report-subtitle{background:#fff;border:1.5px solid #e2e0ef;border-radius:40px;padding:12px 26px;font-size:29px}.iran-fx .report-main{padding:0 32px 20px}.iran-fx .brand-watermark{width:720px;height:720px;opacity:.025}
.fx-board{display:grid;grid-template-columns:1fr 1fr;gap:18px;direction:rtl;height:100%}.fx-half{min-width:0;display:flex;flex-direction:column;border:1.5px solid #e1dff0;border-radius:24px;overflow:hidden;align-self:start}.fx-table{border:0}
.fx-table td{height:86px;padding:0 20px;border-bottom:1px solid #eae8f3;background:#fff}.fx-table tbody tr:nth-child(even) td{background:#faf9fe}.fx-table tbody tr:last-child td{border-bottom:0}.fx-table td:first-child{width:51%;padding-right:20px;padding-left:0}.fx-table td:nth-child(2){width:49%;text-align:left}
.currency-name{display:flex;align-items:center;gap:10px;font-size:32px;white-space:nowrap}.currency-name strong{font-weight:800}.currency-name small{font:600 22px Arial,sans-serif;color:#77708f;line-height:1.45;letter-spacing:.6px}
.currency-flag{width:52px;height:40px;object-fit:cover;border-radius:5px;flex-shrink:0;border:1px solid #d8dbe3}
.iran-fx .currency-flag{width:68px;height:52px;border-radius:8px}.iran-fx .currency-name{gap:12px}.iran-fx .name-stack strong{line-height:1.35}
.fx-table .price{font-size:62px;letter-spacing:-1.3px;line-height:1.15}.fx-unit{height:86px;flex-shrink:0;display:flex;align-items:center;justify-content:center;gap:9px;font-size:28px;color:#595372;flex-wrap:wrap;background:#f0eef8;border-top:1px solid #eae8f3}.fx-unit b{color:#4b3dcb;font-size:36px}.availability-note{font-size:18px;max-width:100%;text-align:center}
.iran-fx .report-footer{height:88px;font-size:22px}.iran-fx .report-footer b{padding-right:32px;border-right:1px solid #fff}
.turkey-gold .report-title{height:156px}.turkey-gold .report-title h1{font-size:68px}.turkey-gold .report-main{padding:24px 44px 0}.turkey-gold .report-footer,.fx-pulse .report-footer{height:88px}
.buy-sell-key{display:flex;align-items:center;gap:20px;font-size:25px;font-weight:800;white-space:nowrap}.buy-sell-key span{display:flex;align-items:center;gap:8px}.buy-sell-key i{width:19px;height:19px;border-radius:50%}.sell-dot{background:#df002e}.buy-dot{background:#00802f}
.turkey-gold-table th{height:76px}.turkey-gold-table th:first-child{width:27%}.turkey-gold-table th:nth-child(2),.turkey-gold-table th:nth-child(3){width:24%}.turkey-gold-table th:nth-child(4){width:13%}.turkey-gold-table th:nth-child(5){width:12%}
.turkey-gold-table .instrument-row td{height:150px;border:0;border-top:10px solid white;background-clip:padding-box}.turkey-gold-table .instrument-name{font-size:33px;gap:14px}.turkey-gold-table .num.sell,.turkey-gold-table .num.buy{font-size:56px;letter-spacing:-1.5px;color:#000}.turkey-gold-table .percentage{font-size:33px}.turkey-gold-table .gold-art{width:62px;height:62px}
.currency-unit{flex:1;display:flex;align-items:center;justify-content:center;gap:16px;font-size:31px;font-weight:800;min-height:70px;color:#464074}.currency-unit b{color:#483ccd}.currency-unit .currency-flag{width:49px;height:36px;order:1}
.fx-pulse .report-title{height:174px}.fx-pulse .report-title h1{font-size:67px;border-color:#fb7472}.fx-pulse .report-title .title-subtitle{font-size:29px}.pulse-period{padding:9px 24px;border-radius:30px;background:#efedfc;color:#3d2dbe;font:800 30px Arial,sans-serif}
.fx-pulse .report-main{padding:40px 32px 0}.fx-pulse .brand-watermark{width:600px;height:600px}.pulse-cards{display:flex;flex-direction:column;gap:32px}.pulse-card{height:306px;border:1.5px solid #d8d9ee;border-radius:24px;background:#fafbff9c;display:grid;grid-template-columns:25% 44% 31%;align-items:center;padding:28px 30px;position:relative}
.pair-identity{display:flex;flex-direction:column;align-items:center;gap:12px}.pair-flags{display:flex;gap:12px}.pair-flags .currency-flag{width:88px;height:66px;border-radius:10px}.pair-identity h2{font:900 43px Arial,sans-serif;margin:6px 0 2px;white-space:nowrap}.pair-identity p{font-size:27px;font-weight:800;color:#4d486d;margin:0;white-space:nowrap}
.rate-block{text-align:center;display:flex;flex-direction:column;align-items:center;gap:0}.rate-block .pulse-rate{font-size:88px;letter-spacing:-2.5px;line-height:1.4;color:#000}.rate-block small{font-size:31px;font-weight:800;color:#514b78;white-space:nowrap}
.movement-panels{display:flex;flex-direction:column;gap:12px;align-items:stretch;padding-right:8px}.movement{border-radius:20px;background:#efedf8;display:flex;align-items:center;justify-content:space-between;gap:12px;height:102px;padding:0 18px;font-size:27px;font-weight:800;white-space:nowrap;color:#555078}.movement .percentage{font-size:38px}.movement .num{font-size:38px}.movement:has(.up){background:#e1f4eb}.movement:has(.down){background:#fff0f2}
'''

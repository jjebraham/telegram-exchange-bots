"""Offline Kiani customer-rate images, using the existing producer's text.

No rate fetching, conversion or pricing calculation takes place here.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import escape, unescape
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from kiani_posts import gregorian_to_jalali, JALALI_MONTHS, PERSIAN_WEEKDAYS
from market_images import _asset_data, _font_css

KIANI_IMAGE_POSTS = frozenset({'kiani-rates', 'kiani-try', 'kiani-examples', 'kiani-examples-reverse'})
ISTANBUL = ZoneInfo('Europe/Istanbul')
FA = str.maketrans('0123456789,.', '۰۱۲۳۴۵۶۷۸۹٬٫')
NUM = r'(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|[1-9][0-9]*)'
CROSS = r'(?:[0-9]+)(?:\.[0-9]{1,2})?'
ASSETS = Path(__file__).with_name('kiani_image_assets')


@dataclass(frozen=True)
class CustomerBoard:
    try_buy: str
    try_sell: str
    usdt_buy: str
    usdt_sell: str
    lira_to_usdt: str
    usdt_to_lira: str
    clock: str
    order: str


@dataclass(frozen=True)
class TryBoard:
    buy: str
    sell: str
    source_date: str
    clock: str
    telegram: str
    whatsapp: str


@dataclass(frozen=True)
class ConverterBoard:
    rows: tuple[tuple[str, str], ...]
    basis: str
    basis_label: str
    order: str


def one(pattern: str, text: str):
    matches = re.findall(pattern, text, re.M)
    if len(matches) != 1:
        raise ValueError('Missing or repeated Kiani source field')
    return matches[0]


def positive(value: str) -> str:
    if not re.fullmatch(NUM + r'|'+ CROSS, value):
        raise ValueError('Malformed Kiani price')
    number = Decimal(value.replace(',', ''))
    if not number.is_finite() or number <= 0:
        raise ValueError('Kiani price must be positive')
    return value


def parse_customer_board(text: str) -> CustomerBoard:
    if '<b>صرافی کیانی | نرخ امروز</b>' not in text:
        raise ValueError('Unrecognized Kiani customer board')
    rows = re.findall(r'(از ما می‌خرید|به ما می‌فروشید): <b>(' + NUM + r')</b> تومان', text)
    if [row[0] for row in rows] != ['از ما می‌خرید', 'به ما می‌فروشید'] * 2:
        raise ValueError('Kiani board requires four ordered customer rates')
    prices = [positive(row[1]) for row in rows]
    first = positive(one(r'لیر ← تتر: <b>(' + CROSS + r')</b> لیر', text))
    second = positive(one(r'تتر ← لیر: <b>(' + CROSS + r')</b> لیر', text))
    clock = one(r'<code>((?:[01]\d|2[0-3]):[0-5]\d)</code> استانبول', text)
    order = one(r'سفارش: (@[A-Za-z][A-Za-z0-9_]{4,31})', text)
    return CustomerBoard(*prices, first, second, clock, order)


def parse_try_board(text: str) -> TryBoard:
    table = one(r'<pre>([\s\S]*?)</pre>', text)
    rows = [line.strip() for line in table.splitlines() if line.strip()]
    if len(rows) != 2:
        raise ValueError('Kiani TRY board needs exactly two prices')
    buy = one(r'^🟩 BUY\s+TL (' + NUM + r') = خرید لیر از ما$', rows[0])
    sell = one(r'^🟥 SELL\s+TL (' + NUM + r') = فروش لیر به ما$', rows[1])
    date, clock = one(r'📆 <b>([^<|]+) \| ((?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d)</b>', text)
    links = re.findall(r'href="([^"]+)"', text)
    if len(links) != 2:
        raise ValueError('Kiani TRY contact links are missing')
    telegram, whatsapp = map(unescape, links)
    for link, host in ((telegram, 't.me'), (whatsapp, 'wa.me')):
        parsed = urlsplit(link)
        if parsed.scheme != 'https' or parsed.hostname != host or not re.fullmatch(r'/[A-Za-z0-9_]+', parsed.path) or parsed.query or parsed.fragment:
            raise ValueError('Unrecognized Kiani contact link')
    return TryBoard(positive(buy), positive(sell), date, clock, telegram, whatsapp)


def parse_converter(kind: str, text: str) -> ConverterBoard:
    receive_try = kind == 'kiani-examples'
    title = 'برای دریافت این مقدار لیر' if receive_try else 'برای دریافت این مقدار تومان'
    if title not in text:
        raise ValueError('Kiani calculator direction does not match its post type')
    table = one(r'<pre>([\s\S]*?)</pre>', text)
    lines = [line.replace('\u200e', '').strip() for line in table.splitlines() if line.strip()]
    expected_header = ['TL', 'TOMAN'] if receive_try else ['TOMAN', 'TL']
    if not lines or lines[0].split() != expected_header or len(lines) != 4:
        raise ValueError('Unrecognized Kiani calculator columns or row count')
    expected_amounts = ('10,000', '50,000', '100,000') if receive_try else ('50,000,000', '100,000,000', '500,000,000')
    rows = []
    for line, amount in zip(lines[1:], expected_amounts):
        match = re.fullmatch('(' + NUM + r')\s+(' + NUM + ')', line)
        if not match or match[1] != amount:
            raise ValueError('Kiani calculator amounts are missing or out of order')
        rows.append((positive(match[1]), positive(match[2])))
    label = 'فروش' if receive_try else 'خرید'
    basis = positive(one('بر اساس نرخ ' + label + r' فعلی: <b>(' + NUM + r')</b> تومان', text))
    order = one(r'ثبت سفارش: (@[A-Za-z][A-Za-z0-9_]{4,31})', text)
    return ConverterBoard(tuple(rows), basis, label, order)


def logo_data() -> str:
    blob = (ASSETS / 'kiani-logo.svg').read_bytes()
    root = ET.fromstring(blob)
    for element in root.iter():
        if element.tag.rsplit('}', 1)[-1] in {'script', 'foreignObject'}:
            raise ValueError('Unsafe Kiani logo asset')
        for key, value in element.attrib.items():
            if key.lower().startswith('on') or (key.rsplit('}', 1)[-1] == 'href' and not value.startswith(('#', 'data:image/png;base64,'))):
                raise ValueError('Kiani logo must contain only bundled artwork')
    return 'data:image/svg+xml;base64,' + base64.b64encode(blob).decode('ascii')


def logo(size: str = '') -> str:
    return '<span class="brand-logo ' + size + '" role="img" aria-label="Kiani" style="--logo:url(\'' + logo_data() + '\')"></span>'


def flag(country: str) -> str:
    return '<img class="flag" src="' + _asset_data('flags/' + country + '.svg') + '" alt="' + country.upper() + '">'


TETHER = '<svg class="tether" viewBox="0 0 60 60" aria-label="USDT"><circle cx="30" cy="30" r="29" fill="#26a17b"/><path d="M17 13h26v8H34v6c13 .4 18 2.1 18 5s-7.8 4.9-18 5.2V49h-8V37.2C15.8 36.9 8 34.8 8 32s5-4.6 18-5v-6h-9zm9 16c-9.8.3-15 1.4-15 3 0 1.9 8.5 3.1 19 3.1S49 33.9 49 32c0-1.6-5.2-2.7-15-3v4h-8z" fill="white"/></svg>'
ARROW = '<svg class="route-arrow" viewBox="0 0 60 36" aria-hidden="true"><path d="M54 18H7m15-13L7 18l15 13" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def amount(value: str, *, latin: bool = False, field: str = '') -> str:
    return '<span class="amount" data-fit data-field="' + escape(field) + '" data-value="' + escape(value) + '" dir="ltr">' + escape(value if latin else value.translate(FA)) + '</span>'


def dates(now: datetime) -> tuple[str, str]:
    year, month, day = gregorian_to_jalali(now.year, now.month, now.day)
    jalali = f'{PERSIAN_WEEKDAYS[now.weekday()]} · {day} {JALALI_MONTHS[month]} {year}'.translate(FA)
    english = now.strftime('%a · %d %b %Y')
    return jalali, english


def header() -> str:
    return '<div class="top-rule"></div><div class="brand-row"><span class="brand-lockup">' + logo() + '<b>صرافی کیانی</b></span><b class="site" dir="ltr">kiani.exchange</b></div>'


def footer(clock: str, order: str = '@Kianiexchangebot') -> str:
    return '<footer><div class="footer-clock" data-field="source-clock">استانبول · <span dir="ltr">' + escape(clock.translate(FA)) + '</span></div><div class="order">ثبت سفارش <b dir="ltr">' + escape(order) + '</b></div></footer>'


def board_body(data: CustomerBoard, now: datetime) -> str:
    jalali, english = dates(now)
    hero = '<div class="board-hero">' + logo('large') + '<h1>صرافی کیانی</h1><div class="date">' + escape(jalali) + '<br><span dir="ltr">' + escape(english) + '</span></div></div>'
    cards = []
    for name, icon, buy, sell, code in (('لیر ترکیه', flag('tr'), data.try_buy, data.try_sell, 'try'), ('تتر (USDT)', TETHER, data.usdt_buy, data.usdt_sell, 'usdt')):
        rows = ''
        for label, value, side in (('از ما می‌خرید', buy, 'buy'), ('به ما می‌فروشید', sell, 'sell')):
            rows += '<div class="quote-row"><div class="quote-label"><i class="dot ' + side + '"></i>' + label + '</div><div class="quote-value">' + amount(value, field=code + '-' + side) + '<small>تومان</small></div></div>'
        cards.append('<section class="card quote-card"><h2>' + icon + name + '</h2>' + rows + '</section>')
    cross = '<section class="card cross-card"><h2>نرخ تبدیل</h2>'
    for label, value, key in (('لیر به تتر', data.lira_to_usdt, 'lira-to-usdt'), ('تتر به لیر', data.usdt_to_lira, 'usdt-to-lira')):
        cross += '<div class="cross-row"><strong>' + label + '</strong><div>' + amount(value, field=key) + '<small>لیر</small></div></div>'
    return hero + '<main class="board-cards">' + ''.join(cards) + cross + '</section></main>' + footer(data.clock, data.order)


def try_body(data: TryBoard, now: datetime) -> str:
    title = '<div class="section-title"><h1>' + flag('tr') + 'نرخ لیر ترکیه</h1><p>نرخ مشتری صرافی کیانی · تومان برای هر لیر</p></div>'
    cards = ''
    for label, value, side in (('خرید لیر از ما', data.buy, 'buy'), ('فروش لیر به ما', data.sell, 'sell')):
        cards += '<section class="card focus-card ' + side + '"><h2>' + label + '</h2>' + amount(value, latin=True, field='try-' + side) + '<small>تومان</small></section>'
    telegram = urlsplit(data.telegram).path.strip('/')
    phone = urlsplit(data.whatsapp).path.strip('/')
    if re.fullmatch(r'90\d{10}', phone):
        phone = '+90 ' + phone[2:5] + ' ' + phone[5:8] + ' ' + phone[8:10] + ' ' + phone[10:]
    contact = '<section class="contact"><h2>لطفاً قبل از واریز هماهنگ کنید</h2><p dir="ltr">Telegram: <b>t.me/' + escape(telegram) + '</b></p><p dir="ltr">WhatsApp: <b>' + escape(phone) + '</b></p></section>'
    date = '<div class="source-date">' + escape(data.source_date.translate(FA)) + '</div>'
    return header() + title + '<main class="focus-cards">' + cards + '</main>' + contact + date + footer(data.clock)


def converter_body(kind: str, data: ConverterBoard, now: datetime) -> str:
    receive_try = kind == 'kiani-examples'
    pay_unit, receive_unit = ('تومان', 'لیر') if receive_try else ('لیر', 'تومان')
    origin, destination = ('ایران', 'ترکیه') if receive_try else ('ترکیه', 'ایران')
    from_flag, to_flag = ('ir', 'tr') if receive_try else ('tr', 'ir')
    # Iran's flag is an original simple SVG, because only the existing two
    # transaction countries are needed by this template.
    iran = '<svg class="flag" viewBox="0 0 60 40" aria-label="IR"><rect width="60" height="13.33" fill="#239f40"/><rect y="13.33" width="60" height="13.34" fill="white"/><rect y="26.67" width="60" height="13.33" fill="#da0000"/><text x="30" y="25" text-anchor="middle" fill="#da0000" font-size="15">☫</text></svg>'
    icon = lambda code: iran if code == 'ir' else flag(code)
    title = '<div class="section-title converter-title"><h1>حواله ' + pay_unit + ' به ' + receive_unit + '</h1><p>برای دریافت این مقدار ' + receive_unit + '، چند ' + pay_unit + ' واریز کنید؟</p></div>'
    route = '<div class="transfer-route"><span>' + icon(from_flag) + 'واریز در ' + origin + '</span>' + ARROW + '<span>' + icon(to_flag) + 'دریافت در ' + destination + '</span></div>'
    table = '<main class="converter-cards"><div class="calc-head"><b>واریز می‌کنید</b><i></i><b>دریافت می‌کنید</b></div>'
    for index, (receive, pay) in enumerate(data.rows):
        table += '<section class="card calculator-row"><div class="calc-number pay">' + amount(pay, field='pay-' + str(index)) + '<small>' + pay_unit + '</small></div>' + ARROW + '<div class="calc-number receive">' + amount(receive, field='receive-' + str(index)) + '<small>' + receive_unit + '</small></div></section>'
    basis = '<div class="basis">بر اساس نرخ ' + data.basis_label + ' فعلی: <b data-field="basis" data-value="' + escape(data.basis) + '">' + escape(data.basis.translate(FA)) + '</b> تومان</div>'
    return header() + title + route + table + '</main>' + basis + footer(now.strftime('%H:%M'), data.order)


CSS = r'''
*{box-sizing:border-box}html,body{margin:0;padding:0;background:#edf3ef}body{font-family:AlanVazir,Arial,sans-serif;color:#163e34}.canvas{width:1200px;height:1500px;background:#edf3ef;display:flex;flex-direction:column;overflow:hidden}.content{height:1500px;position:relative;padding:54px 64px 28px;display:flex;flex-direction:column;flex-shrink:0}.top-rule{height:10px;border-radius:10px;background:#198d6b;flex-shrink:0}.brand-row{display:flex;align-items:center;justify-content:space-between;margin-top:24px;font-size:34px;height:64px;flex-shrink:0}.brand-lockup{display:flex;align-items:center;gap:8px}.brand-logo{display:inline-block;width:48px;height:48px;background:#153e34;mask-image:var(--logo);mask-size:contain;mask-repeat:no-repeat;mask-position:center;-webkit-mask-image:var(--logo);-webkit-mask-size:contain;-webkit-mask-repeat:no-repeat;-webkit-mask-position:center;flex-shrink:0}.site{font:700 32px Arial,sans-serif}.brand-logo.large{width:132px;height:132px}.board-hero{display:flex;flex-direction:column;align-items:center;height:322px;flex-shrink:0;padding-top:4px}.board-hero h1{font-size:67px;margin:0;line-height:1.35;font-weight:900}.date{color:#7b9187;text-align:center;font-size:27px;line-height:1.45}.date span{font:26px Arial,sans-serif}.board-cards{display:flex;flex-direction:column;gap:22px}.card{background:white;border-radius:34px;box-shadow:0 13px 28px #123e3410;flex-shrink:0}.quote-card{height:252px;padding:24px 38px}.card h2{margin:0;font-size:40px;line-height:1.4;display:flex;gap:15px;align-items:center}.flag{width:62px;height:42px;object-fit:cover;border-radius:5px;flex-shrink:0}.tether{width:57px;height:57px;flex-shrink:0}.quote-row{display:flex;align-items:center;justify-content:space-between;height:72px;gap:20px}.quote-label{display:flex;align-items:center;gap:17px;font-size:35px;font-weight:600}.dot{width:29px;height:29px;border-radius:50%;display:inline-block}.dot.buy{background:#79b254}.dot.sell{background:#51a5df}.quote-value{display:flex;align-items:baseline;direction:rtl;gap:12px;max-width:52%}.amount{font-weight:900;font-size:70px;line-height:1.3;white-space:nowrap;display:inline-block;max-width:100%;letter-spacing:-1px}.quote-value small{font-size:26px;color:#809288}.cross-card{height:225px;padding:22px 40px}.cross-card h2{font-size:34px;justify-content:center;color:#7b9187;font-weight:600}.cross-row{height:67px;display:flex;justify-content:space-between;align-items:center;font-size:35px}.cross-row>div{display:flex;gap:12px;align-items:baseline}.cross-row .amount{font-size:47px}.cross-row small{font-size:27px}footer{margin-top:auto;border-top:1px solid #d5e3dc;padding-top:20px;display:flex;align-items:center;justify-content:space-between;gap:15px;color:#81948a;font-size:27px;min-height:80px;flex-shrink:0}.order{font-size:25px;display:flex;gap:12px;align-items:center}.order b{font:700 28px Arial,sans-serif;color:#1a8d6a}.section-title{text-align:center;margin-top:40px;margin-bottom:36px;flex-shrink:0}.section-title h1{font-size:67px;line-height:1.4;margin:0;display:flex;align-items:center;justify-content:center;gap:20px;font-weight:900}.section-title p{font-size:30px;color:#7d9187;margin:6px 0 0;line-height:1.6}.focus-cards{display:flex;flex-direction:column;gap:36px}.focus-card{height:312px;text-align:center;padding:30px 30px;border-right:13px solid #1b8e6b}.focus-card h2{justify-content:center;font-size:47px}.focus-card .amount{font:800 162px/1.2 Arial,sans-serif;color:#1b8e6b;letter-spacing:-3px}.focus-card small{display:block;color:#82938b;font-size:26px;line-height:1.1}.focus-card.sell{border-color:#3286aa}.focus-card.sell .amount{color:#3286aa}.contact{text-align:center;margin-top:42px;flex-shrink:0}.contact h2{font-size:38px;margin:0 0 20px}.contact p{font:34px/1.5 Arial,sans-serif;color:#1d906c;margin:3px 0}.source-date{text-align:center;font-size:25px;color:#81948a;margin-top:15px}.kiani-try footer{margin-top:18px}.converter-title{margin-top:46px;margin-bottom:28px}.converter-title h1{font-size:67px}.converter-title p{font-size:32px}.transfer-route{height:116px;display:flex;justify-content:center;align-items:center;gap:28px;border:1px solid #d3e4db;border-radius:26px;font-size:31px;font-weight:750;background:#e5efe9;flex-shrink:0}.transfer-route span{display:flex;align-items:center;gap:13px}.route-arrow{width:64px;height:42px;flex-shrink:0;color:#7fa393}.converter-cards{margin-top:32px;display:flex;flex-direction:column;gap:22px}.calc-head{display:grid;grid-template-columns:1fr 60px 1fr;align-items:center;text-align:center;font-size:31px;color:#668b7a;line-height:1.7}.calculator-row{display:grid;grid-template-columns:minmax(0,1fr) 60px minmax(0,1fr);align-items:center;padding:24px 25px;height:198px;gap:10px;text-align:center}.calc-number{min-width:0;display:flex;flex-direction:column;align-items:center;gap:4px}.calc-number .amount{font-size:70px;width:100%;letter-spacing:-1.2px}.calc-number small{font-size:29px;color:#82938b}.calc-number.receive .amount{color:#1d906c}.calculator-row .route-arrow{width:56px}.basis{margin-top:32px;padding:22px;text-align:center;font-size:30px;background:#e1eee6;border-radius:22px;flex-shrink:0}.basis b{font-size:39px;color:#168561;margin:0 7px}.demo-label{height:40px;line-height:40px;background:#fff0cd;color:#795b13;font-size:23px;text-align:center;font-weight:800;flex-shrink:0}
'''


def kiani_html(kind: str, approved_text: str, *, now: datetime | None = None, demo: bool = False) -> str:
    if kind not in KIANI_IMAGE_POSTS:
        raise ValueError('Unsupported Kiani image post')
    if now is not None and now.tzinfo is None:
        raise ValueError('Kiani rendering time must include its timezone')
    local = (now or datetime.now(ISTANBUL)).astimezone(ISTANBUL)
    if kind == 'kiani-rates':
        body = '<div class="top-rule"></div>' + board_body(parse_customer_board(approved_text), local)
    elif kind == 'kiani-try':
        body = try_body(parse_try_board(approved_text), local)
    else:
        body = converter_body(kind, parse_converter(kind, approved_text), local)
    label = '<div class="demo-label">نمونه آزمایشی — قیمت‌ها واقعی نیستند</div>' if demo else ''
    height = 1360 if kind == 'kiani-rates' else 1500
    extra = '.canvas{height:' + str(height + (40 if demo else 0)) + 'px}.content{height:' + str(height) + 'px}.cross-row .amount{font-size:54px}.footer-clock{font-size:31px}'
    return '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>' + _font_css() + CSS + extra + '</style></head><body><div class="canvas kiani ' + kind + '">' + label + '<div class="content">' + body + '</div></div></body></html>'


def validate_kiani_layout(page) -> None:
    errors = page.evaluate('''() => {
      const root=document.querySelector('.content').getBoundingClientRect(), errors=[];
      for(const e of document.querySelectorAll('[data-field],.brand-row,.card,h1,.contact,.footer-clock,.order,.basis,.transfer-route')) {
        const r=e.getBoundingClientRect();
        const clipped=['hidden','clip'].includes(getComputedStyle(e).overflowY);
        if(r.left<root.left-.5 || r.right>root.right+.5 || r.bottom>root.bottom+.5 || e.scrollWidth>e.clientWidth+1 || (clipped && e.scrollHeight>e.clientHeight+1)) errors.push(e.dataset.field || e.className || e.tagName);
        const card=e.closest('.card');
        if(card && card!==e) {const c=card.getBoundingClientRect(); if(r.left<c.left-.5 || r.right>c.right+.5 || r.top<c.top-.5 || r.bottom>c.bottom+.5) errors.push('field outside card');}
      }
      for(const image of document.images) if(!image.complete || !image.naturalWidth) errors.push('missing image');
      if(!document.fonts.check('900 40px AlanVazir')) errors.push('missing Persian font');
      return errors;
    }''')
    if errors:
        raise RuntimeError('Kiani image layout overflow or missing artwork: ' + ', '.join(errors))


def screenshot(html: str, target: Path) -> None:
    from playwright.sync_api import sync_playwright
    executable = os.environ.get('KIANI_CHROMIUM_PATH') or os.environ.get('ALANCHANDE_CHROMIUM_PATH') or shutil.which('chromium') or shutil.which('google-chrome') or None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=executable, args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': 1200, 'height': 1600}, device_scale_factor=2)
            page.route('**/*', lambda route: route.abort())
            page.set_content(html, wait_until='load')
            page.evaluate('document.fonts.ready')
            page.evaluate('() => Promise.all([...document.images].map(i=>i.decode()))')
            page.evaluate('''() => {for(const e of document.querySelectorAll('[data-fit]')) {let size=parseFloat(getComputedStyle(e).fontSize); while(e.scrollWidth>e.clientWidth+1 && size>44) {e.style.fontSize=(--size)+'px';}}}''')
            validate_kiani_layout(page)
            page.locator('.canvas').screenshot(path=str(target))
        finally:
            browser.close()


def render_kiani_png(kind: str, approved_text: str, output: Path | str, *, now: datetime | None = None, demo: bool = False) -> Path:
    html = kiani_html(kind, approved_text, now=now, demo=demo)
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if importlib.util.find_spec('playwright') and os.environ.get('ALANCHANDE_RENDER_FORCE_WORKER') != '1':
        screenshot(html, target)
    else:
        python = Path(os.environ.get('KIANI_RENDER_PYTHON') or os.environ.get('ALANCHANDE_RENDER_PYTHON') or Path.home() / '.venvs/alanchande-images/bin/python')
        if not python.is_file():
            raise RuntimeError('Kiani image renderer environment is unavailable')
        result = subprocess.run([str(python), str(Path(__file__).resolve()), '--render-worker', str(target)],
                                input=html, text=True, encoding='utf-8', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                                capture_output=True, timeout=75)
        if result.returncode:
            raise RuntimeError('Kiani image render failed before sending: ' + result.stderr[-500:])
    if not target.is_file() or not 5000 <= target.stat().st_size <= 9_500_000:
        raise RuntimeError('Kiani image size is outside Telegram photo limits')
    return target


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--render-worker':
        raise SystemExit('Usage: kiani_images.py --render-worker OUTPUT.png')
    screenshot(sys.stdin.read(), Path(sys.argv[2]).resolve())

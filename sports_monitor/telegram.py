from datetime import datetime, timezone
from html import escape
import requests
from .stores import NAMES

PERSIAN = str.maketrans('0123456789,.', '۰۱۲۳۴۵۶۷۸۹٬٫')
REASONS = {'new': 'پیشنهاد جدید', 'price_drop': 'کاهش بیشتر قیمت', 'restock': 'موجود شد', 'sizes': 'سایزهای جدید'}


def price(cents):
    return f'{cents / 100:,.2f}'.translate(PERSIAN)


def item(product, reason):
    badge = '🔥 تخفیف ویژه' if product.discount >= 50 else '🏷 تخفیف'
    percent = str(int(product.discount)).translate(PERSIAN)
    checked = datetime.fromtimestamp(product.observed_at, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return (f'👟 <b>{escape(product.name[:180])}</b>\n'
            f'📏 سایزهای موجود: {escape("، ".join(product.sizes))}\n'
            f'🏪 {escape(NAMES[product.store])} | {REASONS[reason]}\n'
            f'<s>{price(product.original)}</s> ← <b>{price(product.sale)} لیر</b>\n'
            f'{badge}: <b>{percent}٪</b>\n'
            f'🔗 <a href="{escape(product.url, quote=True)}">مشاهده و خرید از فروشگاه</a>\n'
            f'🕒 بررسی: {checked}')


def batches(deals, group_size=7):
    if not 5 <= group_size <= 10:
        raise ValueError('group_size must be between 5 and 10')
    header = '🔥 <b>تخفیف‌های ورزشی ترکیه</b>\n\n'
    footer = '\n\nقیمت و موجودی مربوط به زمان بررسی است و ممکن است تغییر کند.'
    chunks, products = [], []
    for p, reason in deals:
        chunk = item(p, reason)
        if len((header + chunk + footer).encode('utf-16-le')) // 2 > 3900:
            raise ValueError('Single product message exceeds Telegram limit')
        candidate = header + '\n\n━━━━━━━━━━\n\n'.join(chunks + [chunk]) + footer
        if chunks and (len(products) >= group_size or len(candidate.encode('utf-16-le')) // 2 > 3900):
            yield header + '\n\n━━━━━━━━━━\n\n'.join(chunks) + footer, products
            chunks, products = [], []
        chunks.append(chunk)
        products.append(p)
    if chunks:
        yield header + '\n\n━━━━━━━━━━\n\n'.join(chunks) + footer, products


class DeliveryError(RuntimeError):
    def __init__(self, message, ambiguous=False):
        super().__init__(message)
        self.ambiguous = ambiguous


def send(token, destination, text):
    # Telegram has no idempotency key. Never auto-retry ambiguous POSTs.
    try:
        response = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                                 json={'chat_id': destination, 'text': text, 'parse_mode': 'HTML',
                                       'link_preview_options': {'is_disabled': True}},
                                 timeout=(10, 35), allow_redirects=False)
    except requests.RequestException:
        raise DeliveryError('Telegram delivery uncertain; reconcile the outbox before retrying', True) from None
    try:
        result = response.json()
    except ValueError:
        raise DeliveryError('Telegram returned an unreadable response', True) from None
    if response.status_code == 200 and result.get('ok') is True:
        try:
            return int(result['result']['message_id'])
        except (KeyError, TypeError, ValueError):
            raise DeliveryError('Telegram acknowledgement missing message ID', True) from None
    raise DeliveryError(f'Telegram rejected request (HTTP {response.status_code})', response.status_code >= 500)

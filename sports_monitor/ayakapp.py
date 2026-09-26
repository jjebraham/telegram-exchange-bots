"""Read recent, retailer-specific Ayakapp product pages as a limited fallback.

Only public HTML and Product JSON-LD are used. No scripts are executed and no
private endpoints or access controls are bypassed. The mirror's update label
must be recent; unknown or day-granularity timestamps fail closed.
"""
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urljoin, urlsplit

from .model import Product, canonical, money
from .parsing import documents, running_shoe, walk
from .stores import STORES


ROOT = 'https://ayakapp.com'
STORE_SLUGS = {
    'sneaks': 'sneaksup',
    'koray': 'korayspor',
    'yali': 'yalispor',
    'adidas': 'adidas',
}
STORE_NAMES = {store.key: store.name for store in STORES}
MAX_AGE_SECONDS = 24 * 60 * 60


class AyakappParseError(ValueError):
    pass


def listing_url(store):
    try:
        slug = STORE_SLUGS[store]
    except KeyError as exc:
        raise AyakappParseError('No Ayakapp retailer mapping') from exc
    return f'{ROOT}/firmalar/{slug}'


def _normal(value):
    value = unicodedata.normalize('NFKD', str(value).casefold())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return re.sub(r'[^a-z0-9]+', '', value)


def discover_products(store, page_url, html):
    """Return unique Ayakapp offer pages for the requested retailer only."""
    slug = STORE_SLUGS.get(store)
    if not slug:
        raise AyakappParseError('No Ayakapp retailer mapping')
    if urlsplit(page_url).hostname != 'ayakapp.com':
        raise AyakappParseError('Unexpected Ayakapp listing host')
    soup, _ = documents(html)
    result, seen = [], set()
    for anchor in soup.select('a[href]'):
        target = urljoin(page_url, anchor['href'])
        parts = urlsplit(target)
        if (parts.scheme != 'https' or parts.hostname != 'ayakapp.com'
                or '/varyasyonlar/' not in parts.path
                or not parts.path.rstrip('/').rsplit('/', 1)[-1].casefold().startswith(slug + '-')):
            continue
        target = canonical(target)
        if target not in seen:
            seen.add(target)
            result.append(target)
    return result


def _updated_age_seconds(soup):
    text = soup.get_text(' ', strip=True)
    match = re.search(
        r'\b(bugün|dün|\d+\s+(?:saniye|dakika|saat|gün|hafta|ay|yıl)\s+önce)\s+güncelleme\b',
        text, re.IGNORECASE)
    if not match:
        raise AyakappParseError('Missing Ayakapp product update time')
    value = match.group(1).casefold()
    if value == 'bugün':
        return 0
    # Day, week, and month labels describe a range; they cannot prove that the
    # record is no more than 24 hours old.
    age = re.fullmatch(r'(\d+)\s+(saniye|dakika|saat)\s+önce', value)
    if not age:
        raise AyakappParseError('Ayakapp product data is too old or imprecise')
    amount = int(age.group(1))
    seconds = amount * {'saniye': 1, 'dakika': 60, 'saat': 3600}[age.group(2)]
    if seconds > MAX_AGE_SECONDS:
        raise AyakappParseError('Ayakapp product data is older than 24 hours')
    return seconds


def _available_sizes(product):
    properties = product.get('additionalProperty', [])
    if isinstance(properties, dict):
        properties = [properties]
    for prop in properties:
        if not isinstance(prop, dict) or _normal(prop.get('name', '')) != 'availablesizes':
            continue
        value = prop.get('value')
        if isinstance(value, list):
            values = value
        elif isinstance(value, str):
            values = re.split(r'\s*[,;\n]\s*', value.strip())
        else:
            break
        return tuple(str(item).strip() for item in values if str(item).strip())
    raise AyakappParseError('Missing explicit available-size list')


def _savings(soup):
    match = re.search(r'(?:₺\s*)?([\d.,]+)\s*(?:₺|TL)?\s+tasarruf\b',
                      soup.get_text(' ', strip=True), re.IGNORECASE)
    return money(match.group(1), turkish=True) if match else None


def _discount_percent(soup):
    text = soup.get_text(' ', strip=True)
    match = re.search(
        r'(?:%\s*(\d{1,3})|(?<!\d)(\d{1,3})\s*%)\s*(?:gerçek\s+fırsat|indirim)\b'
        r'|\b(?:gerçek\s+fırsat|indirim)\s*(?:%\s*(\d{1,3})|(\d{1,3})\s*%)',
        text, re.IGNORECASE)
    if not match:
        return None
    return int(next(value for value in match.groups() if value is not None))


def _direct_store_url(store, soup):
    expected = urlsplit(next(item.root for item in STORES if item.key == store)).hostname
    expected = expected.removeprefix('www.')
    for anchor in soup.select('a[href]'):
        target = urljoin(ROOT, anchor['href'])
        parts = urlsplit(target)
        if (parts.scheme == 'https' and parts.hostname
                and parts.hostname.removeprefix('www.') == expected):
            return canonical(target)
    raise AyakappParseError('Missing direct retailer product link')


def parse_product(store, url, html, observed_at):
    if urlsplit(url).hostname != 'ayakapp.com':
        raise AyakappParseError('Unexpected Ayakapp product host')
    soup, docs = documents(html)
    products = [node for node in walk(docs)
                if node.get('@type') == 'Product' and isinstance(node.get('offers'), dict)]
    product = next((node for node in products
                    if urlsplit(node.get('url', '')).hostname == 'ayakapp.com'
                    and urlsplit(node.get('url', '')).path.rstrip('/') == urlsplit(url).path.rstrip('/')),
                   None)
    if product is None:
        raise AyakappParseError('No matching Ayakapp Product JSON-LD record')

    offer = product['offers']
    seller = offer.get('seller', {})
    seller_name = _normal(seller.get('name', '')) if isinstance(seller, dict) else ''
    seller_aliases = {
        'sneaks': {'sneaksup'}, 'koray': {'korayspor'},
        'yali': {'yalispor'}, 'adidas': {'adidas'},
    }
    if seller_name not in seller_aliases.get(store, {_normal(STORE_NAMES[store])}):
        raise AyakappParseError('Ayakapp offer belongs to a different retailer')
    if offer.get('priceCurrency') != 'TRY' or not offer.get('price'):
        raise AyakappParseError('Missing or non-TRY Ayakapp offer price')

    age = _updated_age_seconds(soup)
    # The date is a relative label rather than an exact timestamp. "Today" and
    # hour/minute labels are recent enough; older calendar labels fail closed.
    if age > MAX_AGE_SECONDS:
        raise AyakappParseError('Ayakapp product data is older than 24 hours')

    sale = money(offer['price'])
    savings = _savings(soup)
    shown_discount = _discount_percent(soup)
    if savings is None and shown_discount is not None:
        raise AyakappParseError('Discount shown without a verifiable original price')
    original = sale + savings if savings is not None else sale
    if original <= 0 or sale > original:
        raise AyakappParseError('Invalid Ayakapp price range')
    if shown_discount is not None:
        calculated = int((Decimal(100) * (original - sale) / original)
                         .quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        if abs(calculated - shown_discount) > 1:
            raise AyakappParseError('Ayakapp discount badge does not match price and savings')

    availability = str(offer.get('availability', ''))
    sizes = _available_sizes(product)
    if availability.endswith('/OutOfStock'):
        sizes = ()
    elif not availability.endswith('/InStock') or not sizes:
        raise AyakappParseError('Ayakapp does not verify in-stock sizes')

    name = str(product.get('name', '')).strip()
    if not name:
        raise AyakappParseError('Missing Ayakapp product name')
    category = product.get('category', '')
    taxonomy = category if isinstance(category, list) else [category]
    direct_url = _direct_store_url(store, soup)
    sku = product.get('sku') or product.get('productID')
    if not sku:
        raise AyakappParseError('Missing Ayakapp product SKU')
    return Product(store, str(sku), name, original, sale, direct_url, sizes,
                   observed_at, running_shoe=running_shoe(name, taxonomy),
                   verify_url=canonical(url), source='ayakapp')

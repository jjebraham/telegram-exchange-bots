"""Read public embedded JSON; never execute remote JavaScript.

Next Flight references are resolved only within the fetched document. Unknown
stock schemas fail closed, rather than inferring availability from size names.
"""
import json
import re
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup
from .model import Product, canonical, money


class ParseError(ValueError):
    pass


def running_shoe(name, taxonomy=()):
    """Require a shoe title plus an explicit running category or known running model."""
    def normalize(text):
        text = unicodedata.normalize('NFKD', str(text).casefold().replace('ı', 'i'))
        text = ''.join(c for c in text if not unicodedata.combining(c))
        return re.sub(r'[^a-z0-9]+', ' ', text).strip()

    title = normalize(name)
    if not re.search(r'\b(ayakkabi|shoe|shoes|sneaker|sneakers|trainer)\b', title):
        return False
    categories = ' '.join(normalize(x) for x in taxonomy if x)
    if re.search(r'\b(kosu|running|road running|trail running)\b', categories):
        return True
    models = (
        r'\bultraboost\b', r'\badizero\b', r'\bsupernova\b', r'\bduramo\b', r'\bpureboost\b',
        r'\bpegasus\b', r'\bvomero\b', r'\bdownshifter\b', r'\bwinflo\b', r'\binvincible\b',
        r'\balphafly\b', r'\bvaporfly\b', r'\bstreakfly\b', r'\bquest\b', r'\bstructure\b',
        r'\bgel nimbus\b', r'\bgel kayano\b', r'\bnovablast\b', r'\bcumulus\b', r'\bgt 2000\b',
        r'\bsuperblast\b', r'\bnoosa tri\b', r'\bmagic speed\b', r'\bmetaspeed\b', r'\btrabuco\b',
        r'\bclifton\b', r'\bbondi\b', r'\bspeedgoat\b', r'\brincon\b', r'\bchallenger\b',
        r'\b1080\b', r'\bfresh foam 880\b', r'\bfresh foam 860\b', r'\bfresh foam more\b',
        r'\bfuelcell rebel\b', r'\bsc elite\b', r'\bsc trainer\b', r'\bdeviate nitro\b',
        r'\bvelocity nitro\b', r'\bmagnify nitro\b', r'\bforeverrun\b', r'\bfast r nitro\b',
        r'\btriumph\b', r'\bkinvara\b', r'\bendorphin\b', r'\bperegrine\b', r'\bghost\b',
        r'\bglycerin\b', r'\badrenaline gts\b', r'\bhyperion\b', r'\bcascadia\b', r'\bwave rider\b',
    )
    return any(re.search(pattern, title) for pattern in models)


def _taxonomy(product):
    values = []
    keys = ('category', 'subcategory', 'shortName', 'sportType', 'routeDescription',
            'integration_sport', 'integration_category', 'integration_sub_category',
            'integration_urun_grup', 'integration_ana_grup', 'integration_alt_grup',
            'filterable_urun_grup', 'categoryName', 'category_name', 'department')
    for key in keys:
        value = product.get(key)
        if isinstance(value, (str, int)):
            values.append(str(value))
        elif isinstance(value, list):
            values.extend(str(v.get('name', '')) if isinstance(v, dict) else str(v) for v in value)
    attrs = product.get('attributes', {})
    if isinstance(attrs, dict):
        values.extend(str(attrs[k]) for k in keys if attrs.get(k))
    return tuple(values)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def documents(html):
    if html.lstrip().startswith(('{', '[')):
        try:
            return BeautifulSoup('', 'html.parser'), [json.loads(html)]
        except ValueError:
            pass
    soup = BeautifulSoup(html, 'html.parser')
    docs, fragments = [], []
    for script in soup.select('script'):
        text = script.get_text()
        if script.get('type') in ('application/json', 'application/ld+json'):
            try:
                docs.append(json.loads(text))
            except ValueError:
                continue
        match = re.fullmatch(r'self\.__next_f\.push\((.*)\);?', text.strip(), re.S)
        if match:
            try:
                value = json.loads(match[1])
                if value[0] == 1 and isinstance(value[1], str):
                    fragments.append(value[1])
            except (ValueError, IndexError, TypeError):
                continue
    records = {}
    raw = ''.join(fragments).encode('utf-8')
    pos = 0
    while pos < len(raw):
        match = re.match(rb'([0-9a-f]+):', raw[pos:])
        if not match:
            end = raw.find(b'\n', pos)
            pos = end + 1 if end >= 0 else len(raw)
            continue
        key = match[1].decode()
        pos += match.end()
        length = re.match(rb'T([0-9a-f]+),', raw[pos:])
        if length:
            pos += length.end()
            end = pos + int(length[1], 16)
            records[key] = raw[pos:end].decode('utf-8', errors='replace')
            pos = end
            continue
        end = raw.find(b'\n', pos)
        end = end if end >= 0 else len(raw)
        try:
            records[key] = json.loads(raw[pos:end])
        except ValueError:
            pass
        pos = end + 1

    def resolve(value, seen=frozenset(), depth=0):
        if depth > 60:
            return None
        if isinstance(value, str) and re.fullmatch(r'\$[0-9a-f]+', value):
            key = value[1:]
            if key in seen or key not in records:
                return value
            return resolve(records[key], seen | {key}, depth + 1)
        if isinstance(value, dict):
            return {k: resolve(v, seen, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v, seen, depth + 1) for v in value]
        return value
    # Resolve only data-bearing records, not the entire repeated React tree.
    for key, value in records.items():
        if isinstance(value, (dict, list)):
            if any(k in d for d in walk(value) for k in ('product', 'products', 'retail_price', 'sizeOptions', 'initialProducts', 'initialApiProducts', 'initialApiFilters', 'pagination')):
                docs.append(resolve(value, frozenset({key})))
    return soup, docs


def same_path(a, b):
    return urlsplit(a).path.rstrip('/') == urlsplit(b).path.rstrip('/')


def parse_product(store, url, html, observed_at):
    _, docs = documents(html)
    nodes = list(walk(docs))
    def make(sku, name, original, sale, sizes, taxonomy=()):
        return Product(store, str(sku), name, money(original), money(sale), url, tuple(sizes), observed_at,
                       running_shoe=running_shoe(name, taxonomy))

    # Akinon PDP wrapper distinguishes the requested model from recommendations.
    for wrapper in nodes:
        p = wrapper.get('product')
        if not isinstance(p, dict) or 'selected_variant' not in wrapper:
            continue
        if not same_path(p.get('absolute_url', ''), url) and not (html.lstrip().startswith('{') and wrapper is docs[0]):
            continue
        if str(p.get('currency_type', '')).lower() != 'try':
            raise ParseError('Non-TRY price')
        size_groups = [g for g in wrapper.get('variants', []) if isinstance(g, dict)
                       and g.get('attribute_key') in ('integration_size', 'integration_beden', 'filterable_size', 'filterable_beden')]
        if not size_groups:
            raise ParseError('Missing explicit size stock')
        sizes = []
        for group in size_groups:
            for option in group.get('options', []):
                if not isinstance(option.get('in_stock'), bool):
                    raise ParseError('Unknown option stock')
                if option['in_stock'] and option.get('is_selectable') is True:
                    variant = option.get('product', {})
                    if money(variant.get('price', p['price'])) != money(p['price']):
                        continue  # Never advertise a size at another variant's price.
                    sizes.append(option['label'])
        attrs = p.get('attributes', {})
        color = next((str(attrs[k]) for k in ('integration_color_hash', 'integration_renk', 'filterable_renk') if attrs.get(k)), '')
        return make(str(p.get('base_code') or p['pk']) + ':' + color, p['name'], p['retail_price'], p['price'], sizes, _taxonomy(p))

    if store == 'koray':
        for p in nodes:
            if 'stocksByBarcode' not in p or not same_path('/' + str(p.get('routePath', '')).lstrip('/'), url):
                continue
            barcodes = p.get('barcodes', [])
            if not barcodes or any(not b.get('stockTypeValues') for b in barcodes):
                raise ParseError('Missing barcode-to-size mapping')
            stock = p['stocksByBarcode']
            if any(str(b['id']) not in stock for b in barcodes):
                raise ParseError('Incomplete size stock')
            sizes = [' / '.join(v['name'] for v in b['stockTypeValues']) for b in barcodes if stock[str(b['id'])] > 0]
            brand = p.get('brand', {}).get('name', '')
            return make(p.get('sku') or p['id'], (brand + ' ' + p['name']).strip(), p['basePrice'], p['salesPrice'], sizes, _taxonomy(p))

    if store == 'sneaks':
        for p in nodes:
            if 'productName' not in p or not same_path('/' + p.get('slug', ''), url) or 'variants' not in p:
                continue
            price = p['price']
            if price.get('currencyCode') != 'TRY':
                raise ParseError('Non-TRY price')
            variants = [v for v in p['variants'] if v.get('specName') == 'size']
            if not variants or any('quantity' not in v for v in variants):
                raise ParseError('Missing size quantities')
            sizes = [v['specValueName'] for v in variants if v['quantity'] > 0
                     and not v.get('singleSaleDisabled') and money(v['newPrice']) == money(price['newPrice'])]
            if p.get('addToBasketDisabled'):
                sizes = []
            taxonomy = [c.get('name', '') for c in p.get('categories', []) if isinstance(c, dict)]
            return make(p['erpCode'], p['productName'], price['oldPrice'], price['newPrice'], sizes, taxonomy)

    if store == 'yali':
        for p in nodes:
            if 'sizeOptions' not in p or not same_path('/urun/' + p.get('slug', ''), url):
                continue
            options = p['sizeOptions']
            if not isinstance(options, list) or any(not isinstance(o.get('available'), bool) for o in options):
                raise ParseError('Missing live size flags')
            return make(p['productCode'], p['name'], p.get('originalPrice') or p['price'], p['price'],
                        [o['display'] for o in options if o['available']], _taxonomy(p))

    if store == 'adidas':
        # Accept only per-size offers with explicit stock and a list price.
        # AggregateOffer highPrice is NOT a list price.
        for p in nodes:
            if p.get('@type') != 'Product' or not same_path(p.get('url', ''), url):
                continue
            variants = p.get('hasVariant', [])
            if not variants:
                continue
            offers = [(v, v.get('offers', {})) for v in variants]
            if any(not isinstance(o, dict) or o.get('priceCurrency') != 'TRY' for _, o in offers):
                raise ParseError('Unknown variant currency')
            active = [(v, o) for v, o in offers if str(o.get('availability', '')).endswith('/InStock')]
            if not active:
                raise ParseError('No verifiable adidas size prices')
            sale = min(money(o['price']) for _, o in active)
            chosen = [(v, o) for v, o in active if money(o['price']) == sale]
            specs = chosen[0][1].get('priceSpecification', [])
            if isinstance(specs, dict):
                specs = [specs]
            original = next((s['price'] for s in specs if str(s.get('priceType', '')).endswith('ListPrice')), None)
            if original is not None:
                return make(p.get('sku', url), p['name'], original, DecimalPrice(sale), [v['size'] for v, _ in chosen], _taxonomy(p))
    raise ParseError('No supported product with explicit live size stock')


def DecimalPrice(cents):
    return f'{cents // 100}.{cents % 100:02d}'


def discover(store, url, html):
    soup, docs = documents(html)
    links = set()
    catalogs = [n['products'] for n in walk(docs) if isinstance(n.get('products'), list)
                and any(isinstance(p, dict) and ('retail_price' in p or 'salesPrice' in p or 'productName' in p) for p in n['products'])]
    candidates = [p for catalog in catalogs for p in catalog if isinstance(p, dict)] if catalogs else walk(docs)
    for p in candidates:
        path = None
        if 'retail_price' in p and 'name' in p:
            path = p.get('absolute_url')
        elif store == 'koray' and 'salesPrice' in p:
            path = '/' + p.get('routePath', '').lstrip('/')
        elif store == 'sneaks' and 'productName' in p:
            path = '/' + p.get('slug', '')
        elif store == 'yali' and 'productCode' in p and p.get('slug'):
            path = '/urun/' + p['slug']
        if path:
            links.add(urljoin(url, path))
    for a in soup.select('.product-info a[href], .product-image a[href], [data-testid="product-box"] a[href], a[href*="/urun/"], a[href*="-p-"]'):
        links.add(urljoin(url, a['href']))
    if store == 'adidas':
        links.update(urljoin(url, a['href']) for a in soup.select('a[href]') if re.search(r'/[A-Z0-9]{6}\.html', a['href']))
    host = urlsplit(url).hostname
    links = {canonical(u) for u in links if urlsplit(u).hostname == host and urlsplit(u).path != '/'}
    next_pages = {urljoin(url, a['href']) for a in soup.select('a[rel="next"][href], a[aria-label="Next"][href], a[aria-label="Sonraki"][href]')}
    for node in walk(docs):
        page = node.get('pagination')
        if isinstance(page, dict) and isinstance(page.get('current_page'), int) and isinstance(page.get('num_pages'), int):
            if page['current_page'] < page['num_pages']:
                parts = urlsplit(url)
                params = dict(parse_qsl(parts.query))
                params['page'] = str(page['current_page'] + 1)
                next_pages.add(urlunsplit(parts._replace(query=urlencode(params))))
        if store == 'koray' and isinstance(node.get('currentPage'), int) and isinstance(node.get('totalPages'), int):
            if node['currentPage'] < node['totalPages']:
                parts = urlsplit(url)
                params = dict(parse_qsl(parts.query))
                params['page'] = str(node['currentPage'] + 1)
                next_pages.add(urlunsplit(parts._replace(query=urlencode(params))))
        if store == 'yali' and isinstance(node.get('current_page'), int) and isinstance(node.get('last_page'), int):
            if node['current_page'] < node['last_page']:
                # Never follow the internal host exposed in pagination metadata.
                parts = urlsplit(url)
                params = dict(parse_qsl(parts.query))
                params['page'] = str(node['current_page'] + 1)
                next_pages.add(urlunsplit(parts._replace(query=urlencode(params))))
    # Pagination links only: don't crawl arbitrary navigation/query permutations.
    for a in soup.select('a[href]'):
        if re.search(r'[?&](page|sayfa|start)=\d+', a['href']) and (a.get_text(strip=True).isdigit() or a.get('rel') == ['next']):
            next_pages.add(urljoin(url, a['href']))
    return sorted(links), sorted(u for u in next_pages if urlsplit(u).hostname == host)

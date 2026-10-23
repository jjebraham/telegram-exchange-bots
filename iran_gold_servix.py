"""Authenticated Servix corroboration; retain midpoint, source time and quality."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from iran_gold_data import GoldError, SPEC, UTC, fresh, number, stamp

BASE = 'https://servix.cc/api/v1/'
SOURCE = 'https://servix.cc/api/gold'
KEY_FILE = Path.home() / '.local/state/kiani-instagram-iran-gold/servix-api-key'
CODES = {
    'emami': 'SEKKEH_RLS', 'bahar': 'BAHAR_RLS', 'half': 'NIM_SEKKEH_RLS',
    'quarter': 'ROB_SEKKEH_RLS', 'gram_coin': 'GERAMI_SEKKEH_RLS',
    'gold18': 'GOLD_18_RLS', 'mesghal': 'GOLD_MESGHAL_RLS',
}
WARNING = re.compile(r'rateSurf healthStatus=DEGRADED\. Excluded stale sources=([0-9]+), outlier or conflicting sources=([0-9]+)')
META_FIELDS = ('code', 'quoteUnit', 'providers', 'providerSupported', 'latestValueAvailable',
               'latestValue', 'businessTime', 'sourceTime', 'insertTime', 'qualityStatus',
               'qualityMessage', 'availabilityStatus', 'stale')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def key_bytes(path=KEY_FILE):
    if path.is_symlink() or not path.is_file():
        raise GoldError('Servix private key is not configured.', 'not_configured')
    st = path.stat()
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077 or st.st_size > 1024:
        raise GoldError('Servix key ownership or permissions are unsafe.', 'configuration')
    return path.read_bytes()


def clean_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[!-~]{8,1000}', value.strip()):
        raise GoldError('Servix key format is invalid.', 'configuration')
    return value.strip()


def load_key():
    try:
        return clean_key(key_bytes().decode('ascii'))
    except (UnicodeError, OSError):
        raise GoldError('Servix private key cannot be read.', 'configuration') from None


def get_json(path, key):
    # This is a fixed HTTPS service, not a URL proxy. Never forward its key.
    if path != 'assets/supported' and path != 'assets?' + urlencode({'codes': ','.join(CODES.values())}):
        raise GoldError('Unreviewed Servix endpoint.', 'source')
    req = Request(BASE + path, headers={'X-API-Key': clean_key(key), 'Accept': 'application/json',
        'Accept-Encoding': 'identity', 'Cache-Control': 'no-cache', 'User-Agent': 'KianiExchange-GoldVerifier/1.0'})
    try:
        deadline = time.monotonic() + 30
        with build_opener(NoRedirect()).open(req, timeout=12) as response:
            if response.status != 200 or response.url != req.full_url:
                raise GoldError('Servix returned an unexpected response.', 'source')
            chunks, size = [], 0
            while size <= 2_000_000:
                if time.monotonic() >= deadline:
                    raise GoldError('Servix response exceeded its time budget.', 'source_timeout')
                chunk = response.read1(min(65536, 2_000_001 - size))
                if not chunk:
                    break
                chunks.append(chunk); size += len(chunk)
        body = b''.join(chunks)
        if not body or len(body) > 2_000_000:
            raise GoldError('Servix response is empty or oversized.', 'source')
        def bad_constant(_):
            raise GoldError('Servix returned a non-finite number.', 'source')
        data = json.loads(body, parse_float=Decimal, parse_constant=bad_constant)
        return data, hashlib.sha256(body).hexdigest()
    except HTTPError as exc:
        # Never log headers, raw bodies, keys, or arbitrary server error text.
        raise GoldError('Servix HTTP ' + str(exc.code) + '; source excluded.', 'source_http') from None
    except GoldError:
        raise
    except Exception:
        raise GoldError('Servix connection or response parsing failed.', 'source') from None


def check_meta(asset, meta, now):
    if (not isinstance(meta, dict) or meta.get('code') != CODES[asset] or
            meta.get('quoteUnit') != 'RLS' or meta.get('providerSupported') is not True or
            meta.get('latestValueAvailable') is not True or meta.get('stale') is not False or
            meta.get('availabilityStatus') not in {'FRESH', 'AVAILABLE'}):
        raise GoldError('Servix instrument/unit/availability is not verified.', 'quality')
    if meta.get('providers') != ['SERVIX']:
        raise GoldError('Servix declared provider identity changed.', 'quality')
    quality, message = meta.get('qualityStatus'), meta.get('qualityMessage')
    if quality == 'ACCEPTED_WITH_WARNINGS':
        if not isinstance(message, str) or not WARNING.fullmatch(message):
            raise GoldError('Servix has an unreviewed quality warning.', 'quality')
    elif quality != 'ACCEPTED' or message not in (None, ''):
        raise GoldError('Servix quality state is not accepted.', 'quality')
    fresh(stamp(meta.get('businessTime')), now)
    number(meta.get('latestValue'))


def validate_quote(asset, quote, now):
    if (quote.get('code') != CODES[asset] or quote.get('unit') != 'toman' or quote.get('quote_unit') != 'RLS'
            or quote.get('price_basis') != 'midpoint' or quote.get('supplementary') is not True):
        raise GoldError('Servix exact instrument or unit changed.')
    meta = quote.get('catalog_record')
    check_meta(asset, meta, now)
    updated = stamp(quote.get('updated_at'))
    fresh(updated, now)
    if updated != stamp(meta.get('businessTime')):
        raise GoldError('Servix catalog/quote observation times differ.', 'observation_mismatch')
    value, midpoint, bid, ask = [number(quote.get(k)) for k in
                               ('original_rial', 'mid_rial', 'bid_rial', 'ask_rial')]
    price = number(quote.get('price'))
    if value != midpoint or value != number(meta.get('latestValue')) or value != (bid + ask) / 2 or bid > ask:
        raise GoldError('Servix sides and midpoint are inconsistent.')
    if price != value / 10 or number(quote.get('bid')) != bid / 10 or number(quote.get('ask')) != ask / 10:
        raise GoldError('Servix exact rial/toman conversion failed.')
    if (ask - bid) / value > Decimal('0.01'):
        raise GoldError('Servix bid/ask spread exceeds 1%; instrument excluded.', 'spread')
    if not Decimal(SPEC[asset][5]) <= price <= Decimal(SPEC[asset][6]):
        raise GoldError('Servix price is outside conservative toman bounds.')
    if quote.get('source_url') != SOURCE or any(not re.fullmatch('[0-9a-f]{64}', quote.get(k, ''))
                                               for k in ('page_hash', 'catalog_hash')):
        raise GoldError('Servix source identity/evidence changed.')
    return price


def parse(catalog, current, now, catalog_hash, prices_hash):
    if not isinstance(catalog, dict) or not isinstance(catalog.get('assets'), list) or not isinstance(current, list):
        raise GoldError('Servix catalog/price schema changed.', 'source')
    codes = set(CODES.values())
    metas, prices = {}, {}
    for row in catalog['assets']:
        if not isinstance(row, dict):
            raise GoldError('Servix catalog has a malformed row.', 'source')
        if row.get('code') in codes:
            if row['code'] in metas:
                raise GoldError('Servix catalog repeats an instrument.', 'source')
            metas[row['code']] = {k: row.get(k) for k in META_FIELDS}
    for row in current:
        if not isinstance(row, dict) or row.get('code') not in codes or row['code'] in prices:
            raise GoldError('Servix current prices contain unexpected/repeated instruments.', 'source')
        prices[row['code']] = row
    quotes, rejected = {}, {}
    for asset, code in CODES.items():
        try:
            row, meta = prices.get(code), metas.get(code)
            if not isinstance(row, dict) or not isinstance(meta, dict):
                raise GoldError('Servix exact instrument is unavailable.', 'missing')
            check_meta(asset, meta, now)
            if row.get('quoteUnit') != 'RLS':
                raise GoldError('Servix quote unit is not explicitly RLS.')
            value, mid, bid, ask = [number(row.get(k)) for k in ('value', 'midPrice', 'buyPrice', 'sellPrice')]
            meta = dict(meta, latestValue=str(number(meta['latestValue'])))
            quote = dict(code=code, price=str(value / 10), bid=str(bid / 10), ask=str(ask / 10),
                original_rial=str(value), mid_rial=str(mid), bid_rial=str(bid), ask_rial=str(ask),
                unit='toman', quote_unit='RLS', updated_at=stamp(row.get('businessTime')).isoformat(),
                source_url=SOURCE, page_hash=prices_hash, catalog_hash=catalog_hash,
                catalog_record=meta, price_basis='midpoint', supplementary=True)
            validate_quote(asset, quote, now)
            quotes[asset] = quote
        except (GoldError, KeyError, TypeError, ValueError) as exc:
            rejected[asset] = dict(status='blocked', code=exc.code if isinstance(exc, GoldError) else 'invalid',
                detail=str(exc) if isinstance(exc, GoldError) else 'Incomplete Servix quote evidence.')
    return dict(quotes=quotes, rejected=rejected)


def collect(now=None, key=None):
    key = load_key() if key is None else clean_key(key)
    catalog, catalog_hash = get_json('assets/supported', key)
    current, prices_hash = get_json('assets?' + urlencode({'codes': ','.join(CODES.values())}), key)
    # A refresh between the two reads is excluded, never joined to old quality.
    return parse(catalog, current, datetime.now(UTC), catalog_hash, prices_hash)

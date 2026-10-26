"""Official TGJU public JSON transport; prices retain the provider's rial units.

The official frontend's market_request uses call2/call3/call4.tgju.org/ajax.json.
This transport does not decide market quorum, history or publication eligibility.
Those checks remain in the existing publisher. Per-symbol timestamps may describe
an unchanged price from an earlier session; they are not rewritten as new ticks.
"""
from __future__ import annotations

from decimal import Decimal
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

API_HOSTS = ('call4.tgju.org', 'call2.tgju.org', 'call3.tgju.org')


def parse_public_prices(
    payload: dict,
    symbols: tuple[str, ...],
    *,
    allow_missing: frozenset[str] = frozenset(),
) -> dict[str, Decimal]:
    if not isinstance(payload, dict):
        raise ValueError('TGJU public API response is not an object')
    current = payload.get('current')
    if not isinstance(current, dict):
        raise ValueError('TGJU public API has no current-price object')
    prices = {}
    for symbol in symbols:
        item = current.get(symbol)
        if item is None:
            if symbol in allow_missing:
                continue
            raise ValueError('TGJU public API is missing a valid price: ' + symbol)
        if not isinstance(item, dict):
            raise ValueError('TGJU public API has a malformed price row: ' + symbol)
        raw = item.get('p')
        if raw is None and symbol in allow_missing:
            continue
        if not isinstance(raw, str) or not re.fullmatch(r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)', raw):
            raise ValueError('TGJU public API is missing a valid price: ' + symbol)
        value = Decimal(raw.replace(',', ''))
        if not value.is_finite() or value <= 0:
            raise ValueError('TGJU public API price must be positive: ' + symbol)
        prices[symbol] = value
    return prices


def fetch_public_prices(
    symbols: tuple[str, ...],
    timeout: int = 15,
    *,
    allow_missing: frozenset[str] = frozenset(),
) -> dict[str, Decimal]:
    if not symbols or any(not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', value) for value in symbols):
        raise ValueError('Invalid TGJU public API symbol selection')
    if not allow_missing <= frozenset(symbols):
        raise ValueError('Invalid optional TGJU public API symbols')
    errors = []
    for host in API_HOSTS:
        url = 'https://' + host + '/ajax.json?rev=' + uuid4().hex
        request = Request(url, headers={'Accept':'application/json', 'Accept-Encoding':'identity',
                                        'Cache-Control':'no-cache', 'User-Agent':'AlanChande-PublicMarket/1.0'})
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(2_000_001)
        except (HTTPError, URLError, TimeoutError) as error:
            errors.append(host + ': ' + type(error).__name__)
            continue
        if len(raw) > 2_000_000:
            raise ValueError('TGJU public API response exceeds the expected size')
        # A nonempty malformed response fails closed. Iran FX alone may accept
        # one absent non-core quote; gold and all other callers stay strict.
        return parse_public_prices(json.loads(raw), symbols, allow_missing=allow_missing)
    raise RuntimeError('TGJU official API transport unavailable: ' + '; '.join(errors))


def fetch_iran_fx_public(timeout: int = 15) -> dict[str, Decimal]:
    from iran_fx import CURRENCY_ROWS, IRAN_FX_CORE_CODES
    symbols = {code:('price_dollar_rl' if code == 'USD' else 'price_' + code.lower())
               for code, *_ in CURRENCY_ROWS}
    allowed = frozenset(symbol for code,symbol in symbols.items() if code not in IRAN_FX_CORE_CODES)
    values = fetch_public_prices(tuple(symbols.values()), timeout, allow_missing=allowed)
    missing = [code for code,symbol in symbols.items() if symbol not in values]
    if len(missing) > 1 or any(code in IRAN_FX_CORE_CODES for code in missing):
        raise ValueError('TGJU public API is missing required FX prices: ' + ', '.join(missing))
    return {code:values[symbol]/Decimal('10') for code,symbol in symbols.items() if symbol in values}


def fetch_iran_gold_public(timeout: int = 15):
    from iran_gold import COIN_LABELS, PROFILE_SLUGS, IranGoldMarket
    values = fetch_public_prices(tuple(PROFILE_SLUGS.values()), timeout)
    return IranGoldMarket(
        coin_prices_rial={name:values[PROFILE_SLUGS[name]] for name in COIN_LABELS},
        bubble_values_rial={}, gold18_rial=values[PROFILE_SLUGS['طلای ۱۸ عیار']],
        mesghal_rial=values[PROFILE_SLUGS['مثقال طلا']],
    )

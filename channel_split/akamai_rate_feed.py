"""Read-only local Akamai feed validation. No pricing formula or network I/O."""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import stat
import time

FLAG = Path('/etc/kiani-akamai-rates.enabled')
SNAPSHOT = Path('/home/kianirad2020/.local/state/kiani-akamai-rates/snapshot.json')
FLAG_BYTES = b'akamai-restricted-ssh-v2\n'
MAX_AGE = 90
ORDER_MINIMUM_SOURCES = 2
MAX_SOURCE_DEVIATION = Decimal('0.02')
PROVIDERS = {'Nobitex': 'نوبیتکس', 'Wallex': 'والکس', 'Tabdeal': 'تبدیل',
             'Ramzinex': 'رمزینکس', 'Raastin': 'راستین', 'Exir': 'اکسیر', 'Bitpin': 'بیت پین'}
UPSTREAM_SOURCE = 'akamai-restricted-ssh+btcturk'

class FeedUnavailable(RuntimeError):
    pass

def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise FeedUnavailable('invalid numeric feed value') from exc
    if not result.is_finite():
        raise FeedUnavailable('non-finite feed value')
    return result

def stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('timezone absent')
        return parsed.timestamp()
    except (ValueError, TypeError, OverflowError) as exc:
        raise FeedUnavailable('invalid feed timestamp') from exc

def _regular_bytes(path, limit):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit or info.st_mode & 0o022:
                raise FeedUnavailable('unsafe feed file type, size or permissions')
            return stream.read(limit + 1)
    except OSError as exc:
        raise FeedUnavailable('feed file unavailable') from exc

def enabled():
    try:
        FLAG.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise FeedUnavailable('cannot inspect Akamai activation flag') from exc
    if _regular_bytes(FLAG, 100) != FLAG_BYTES:
        raise FeedUnavailable('invalid Akamai activation flag')
    return True

def centre(values):
    values = sorted(values)
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle-1] + values[middle]) / 2

def sources_agree(quotes):
    """Require independent venues to agree on both executable sides within 2%."""
    if len(quotes) < ORDER_MINIMUM_SOURCES:
        return False
    for key in ('buy_toman', 'sell_toman'):
        values = [number(quote.get(key)) for quote in quotes]
        if min(values) <= 0 or max(values) > min(values) * (1 + MAX_SOURCE_DEVIATION):
            return False
    return True


def validate_snapshot(data, *, now=None, minimum_sources=ORDER_MINIMUM_SOURCES):
    if type(minimum_sources) is not int or minimum_sources not in (1, 2, 5):
        raise FeedUnavailable('invalid validation policy')
    now = time.time() if now is None else now
    if (not isinstance(data, dict) or data.get('schema_version') != 2
            or data.get('transport') != 'akamai-restricted-ssh' or data.get('ok') is not True):
        raise FeedUnavailable('Akamai feed has no validated quorum')
    if not -5 <= now - stamp(data.get('generated_at_utc')) <= 35:
        raise FeedUnavailable('Akamai worker snapshot is old or in the future')
    quotes = data.get('quotes')
    if not isinstance(quotes, list) or not minimum_sources <= len(quotes) <= 7:
        raise FeedUnavailable('Akamai feed has too few independent sources for this policy')
    if type(data.get('minimum_sources')) is not int or data['minimum_sources'] != ORDER_MINIMUM_SOURCES:
        raise FeedUnavailable('collector order policy mismatch')
    if type(data.get('source_count')) is not int or data['source_count'] != len(quotes):
        raise FeedUnavailable('Akamai source count mismatch')
    seen, prices, proofs = set(), [], []
    for quote in quotes:
        provider = quote.get('provider')
        if provider not in PROVIDERS or provider in seen or quote.get('exchange') != PROVIDERS[provider]:
            raise FeedUnavailable('unknown or duplicate primary exchange')
        seen.add(provider)
        if quote.get('eligible') is not True or quote.get('market_open') is not True:
            raise FeedUnavailable('failed or closed-market source')
        ask, bid = number(quote.get('buy_toman')), number(quote.get('sell_toman'))
        if not 0 < bid < ask or (ask-bid)/ask > Decimal('0.02'):
            raise FeedUnavailable('invalid executable bid/ask pair')
        if number(quote.get('buy_quantity')) <= 0 or number(quote.get('sell_quantity')) <= 0:
            raise FeedUnavailable('missing positive order-book liquidity')
        proof = stamp(quote.get('freshness_upper_bound_utc'))
        observed = stamp(quote.get('observed_at_utc'))
        if not -5 <= now-proof <= MAX_AGE or not proof <= observed + 5:
            raise FeedUnavailable('stale or future source proof')
        basis = quote.get('freshness_basis')
        if basis == 'exchange_timestamp':
            if provider not in {'Nobitex', 'Exir'} or stamp(quote.get('exchange_timestamp')) != proof:
                raise FeedUnavailable('exchange timestamp provenance mismatch')
        elif basis == 'http_cache_checks+observed_book_change':
            if provider in {'Nobitex', 'Exir'} or quote.get('http_live') is not True:
                raise FeedUnavailable('unconfirmed source liveness')
        else:
            raise FeedUnavailable('unsupported freshness proof')
        if provider == 'Bitpin':
            state_proof = stamp(quote.get('market_state_proof_utc'))
            trade_proof = stamp(quote.get('latest_trade_utc'))
            if (basis != 'http_cache_checks+observed_book_change'
                    or quote.get('endpoint_selector') != 'bitpin_book'
                    or quote.get('exchange_timestamp') is not None
                    or not -5 <= now-state_proof <= MAX_AGE
                    or not -5 <= now-trade_proof <= MAX_AGE
                    or proof > min(state_proof, trade_proof) + 0.001):
                raise FeedUnavailable('Bitpin evidence is stale, missing, or extended')
        prices.append(ask)
        proofs.append(proof)
    if minimum_sources >= ORDER_MINIMUM_SOURCES and not sources_agree(quotes):
        raise FeedUnavailable('independent sources disagree by more than 2%')
    median = centre(prices)
    if any(not median * Decimal('0.92') <= p <= median * Decimal('1.08') for p in prices):
        raise FeedUnavailable('primary source outside existing median tolerance')
    if number(data.get('median_buy_toman')) != median:
        raise FeedUnavailable('feed median mismatch')
    expires = stamp(data.get('valid_until_utc'))
    if not now < expires <= min(proofs) + MAX_AGE + 0.001:
        raise FeedUnavailable('expired feed or extended freshness window')
    return dict(data, median_buy_toman=median, age_seconds=max(0.0, now-min(proofs)),
                oldest_proof_utc=datetime.fromtimestamp(min(proofs), timezone.utc).isoformat(),
                providers=sorted(seen))

def read_validated_feed():
    try:
        data = json.loads(_regular_bytes(SNAPSHOT, 1024*1024))
        return validate_snapshot(data)
    except FeedUnavailable:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation) as exc:
        raise FeedUnavailable('malformed Akamai snapshot') from exc

def validate_shahidi_market(raw):
    feed = read_validated_feed()
    now = time.time()
    age = number(raw.get('market_age_seconds'))
    if (raw.get('transaction_rates_available') is not True
            or raw.get('rate_mode') != 'confirmed'
            or raw.get('trading_minimum_sources') != ORDER_MINIMUM_SOURCES
            or raw.get('market_source') != UPSTREAM_SOURCE
            or raw.get('market_source_count') != len(feed['providers'])
            or raw.get('market_source_providers') != feed['providers']
            or not 0 <= age <= MAX_AGE
            or not now < stamp(raw.get('market_feed_valid_until_utc')) <= now + MAX_AGE + 5):
        raise FeedUnavailable('Shahidi response lacks current Akamai quorum provenance')


# Display policy: one fresh independent source can supply estimates only.
DISPLAY_FLAG = Path('/etc/kiani-akamai-display.enabled')
DISPLAY_FLAG_BYTES = b'akamai-display-minimum-one-v2\n'

def display_enabled():
    if not enabled():
        return False
    try:
        info = DISPLAY_FLAG.lstat()
    except FileNotFoundError:
        return False
    if info.st_uid != 0 or _regular_bytes(DISPLAY_FLAG, 100) not in (DISPLAY_FLAG_BYTES, b'akamai-display-minimum-two-v1\n'):
        raise FeedUnavailable('invalid Akamai display flag')
    return True

def read_display_feed():
    if not display_enabled():
        raise FeedUnavailable('emergency display policy is disabled')
    try:
        data = json.loads(_regular_bytes(SNAPSHOT, 1024*1024))
        quotes = data.get('quotes')
        if not isinstance(quotes, list) or not 1 <= len(quotes) <= 7:
            raise FeedUnavailable('display requires at least one fresh independent source')
        # Worker keeps ok=false and median=null below the transaction quorum.
        # Build a separate view without changing the file or executable reader.
        if data.get('ok') is False:
            if data.get('ok') is not False or data.get('median_buy_toman') is not None:
                raise FeedUnavailable('invalid sub-quorum worker envelope')
            prices = [number(q.get('buy_toman')) for q in quotes]
            data = dict(data, ok=True, median_buy_toman=str(centre(prices)))
        return validate_snapshot(data, minimum_sources=1)
    except FeedUnavailable:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation) as exc:
        raise FeedUnavailable('malformed display snapshot') from exc

def validate_display_market(raw):
    feed = read_display_feed()
    now = time.time()
    age = number(raw.get('market_age_seconds'))
    if (raw.get('rate_mode') != 'indicative'
            or raw.get('transaction_rates_available') is not False
            or raw.get('market_source') != UPSTREAM_SOURCE
            or raw.get('market_source_count') != len(feed['providers'])
            or raw.get('market_source_providers') != feed['providers']
            or not 0 <= age <= MAX_AGE
            or not now < stamp(raw.get('market_feed_valid_until_utc')) <= now + MAX_AGE + 5
            or number(raw.get('USDT_IRR')) != feed['median_buy_toman'] * 10):
        raise FeedUnavailable('display response lacks fresh Akamai provenance')
    markets = raw.get('market_status')
    if not isinstance(markets, dict) or markets.get('usdt', {}).get('available') is not True:
        raise FeedUnavailable('display response has no fresh USDT market')
    for market, keys in [('usdt', ('buy_usdt', 'sell_usdt', 'foreign_payment')),
                         ('try', ('buy_lira', 'sell_lira', 'lira_to_usdt', 'usdt_to_lira'))]:
        state = markets.get(market, {})
        if state.get('available') is not True:
            if market == 'usdt' or any(raw.get(key) is not None for key in keys):
                raise FeedUnavailable('unavailable market contains display prices')
            continue
        market_age = number(state.get('age_seconds'))
        expires = stamp(state.get('valid_until_utc'))
        if (not 0 <= market_age <= MAX_AGE or not now < expires <= stamp(feed['valid_until_utc']) + 0.001
                or any(number(raw.get(key)) <= 0 for key in keys)):
            raise FeedUnavailable('invalid or expired display market')
        if market == 'try':
            try_age = number(raw.get('market_usdt_try_age_seconds'))
            if (not 0 <= try_age <= MAX_AGE or number(raw.get('USDT_TRY')) <= 0
                    or expires > now + MAX_AGE - float(try_age) + 5):
                raise FeedUnavailable('invalid or stale TRY conversion')
    for buy, sell in [('buy_usdt', 'sell_usdt'), ('buy_lira', 'sell_lira'), ('lira_to_usdt', 'usdt_to_lira')]:
        if raw.get(buy) is not None and number(raw[buy]) < number(raw[sell]):
            raise FeedUnavailable('crossed display prices')
    return feed

"""Read the existing Akamai market feed without network calls or pricing adjustments."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import json
import os
from pathlib import Path
import stat

SOURCE = 'akamai-restricted-ssh:usdt-market'
MAX_AGE = 90
SNAPSHOT = Path.home() / '.local/state/kiani-akamai-rates/snapshot.json'
PROVIDERS = {
    'Nobitex': ('نوبیتکس', 'https://nobitex.ir'),
    'Wallex': ('والکس', 'https://wallex.ir'),
    'Tabdeal': ('تبدیل', 'https://tabdeal.org'),
    'Ramzinex': ('رمزینکس', 'https://ramzinex.com'),
    'Raastin': ('راستین', 'https://raastin.com'),
    'Exir': ('اکسیر', 'https://www.exir.io'),
    'Bitpin': ('بیت پین', 'https://bitpin.ir'),
}
QUOTE_FIELDS = ('provider', 'exchange', 'buy_toman', 'sell_toman', 'buy_quantity',
    'sell_quantity', 'eligible', 'market_open', 'observed_at_utc', 'exchange_timestamp',
    'freshness_upper_bound_utc', 'freshness_basis', 'http_live', 'endpoint_selector',
    'market_state_proof_utc', 'latest_trade_utc')


class AkamaiError(RuntimeError):
    pass


def regular_bytes(path, limit, *, root_owned=False):
    """Refuse unsafe local inputs; never execute or modify the upstream collector."""
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        with os.fdopen(os.open(path, flags), 'rb') as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit
                    or info.st_mode & 0o022
                    or info.st_uid not in {0, os.getuid()}
                    or root_owned and info.st_uid != 0):
                raise AkamaiError('Unsafe Akamai feed file type, owner, size or permissions.')
            data = handle.read(limit + 1)
            if len(data) > limit:
                raise AkamaiError('Akamai feed exceeds its size limit.')
            return data
    except OSError:
        raise AkamaiError('Existing Akamai feed or activation flag is unavailable.') from None


def display_minimum():
    if regular_bytes(Path('/etc/kiani-akamai-rates.enabled'), 100, root_owned=True) != b'akamai-restricted-ssh-v2\n':
        raise AkamaiError('Existing Akamai rate feed is not enabled.')
    flag = regular_bytes(Path('/etc/kiani-akamai-display.enabled'), 100, root_owned=True)
    policies = {b'akamai-display-minimum-one-v2\n': 1, b'akamai-display-minimum-two-v1\n': 2}
    if flag not in policies:
        raise AkamaiError('Existing Akamai informational display policy is unavailable.')
    return policies[flag]


def stamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise AkamaiError('Invalid original Akamai feed timestamp.') from None


def number(value):
    try:
        if value is None or isinstance(value, bool):
            raise ValueError()
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0:
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise AkamaiError('Invalid Akamai market price or liquidity.') from None


def validate_evidence(evidence, *, now, collecting=False):
    """Recompute the unadjusted median and preserve original proof/expiry bounds."""
    if (not isinstance(evidence, dict) or evidence.get('schema_version') != 2
            or evidence.get('transport') != 'akamai-restricted-ssh'
            or type(evidence.get('display_minimum')) is not int
            or evidence['display_minimum'] not in {1, 2}):
        raise AkamaiError('Invalid Akamai market-feed provenance or policy.')
    generated = stamp(evidence.get('generated_at_utc'))
    if not -5 <= (now - generated).total_seconds() <= (35 if collecting else MAX_AGE):
        raise AkamaiError('Akamai collector snapshot is stale or dated in the future.')
    quotes = evidence.get('quotes')
    if not isinstance(quotes, list) or not evidence['display_minimum'] <= len(quotes) <= 7:
        raise AkamaiError('Akamai feed has too few or too many quotes for the enabled display policy.')
    if type(evidence.get('source_count')) is not int or evidence['source_count'] != len(quotes):
        raise AkamaiError('Akamai source count does not match the exchange quote list.')
    upstream_minimum = evidence.get('minimum_sources')
    if type(upstream_minimum) is not int or upstream_minimum not in {2, 5}:
        raise AkamaiError('Unsupported Akamai upstream policy; expected the reviewed two- or five-source format.')
    # Both deployed collector revisions are known: legacy five-source quorum,
    # and the newer TWO-source quorum requiring bid AND ask agreement within 2%.
    # Preserve the upstream policy/envelope; never promote ok=false to ok=true.
    seen, asks, bids, proofs, observed = set(), [], [], [], []
    for quote in quotes:
        if not isinstance(quote, dict):
            raise AkamaiError('Invalid Akamai exchange quote.')
        provider = quote.get('provider')
        if (provider not in PROVIDERS or provider in seen or quote.get('exchange') != PROVIDERS[provider][0]
                or quote.get('eligible') is not True or quote.get('market_open') is not True):
            raise AkamaiError('Unknown, duplicate, ineligible or closed Akamai exchange.')
        seen.add(provider)
        ask, bid = number(quote.get('buy_toman')), number(quote.get('sell_toman'))
        if not bid < ask or (ask - bid) / ask > Decimal('0.02'):
            raise AkamaiError('Akamai exchange bid/ask pair is crossed or too wide.')
        number(quote.get('buy_quantity')); number(quote.get('sell_quantity'))
        proof = stamp(quote.get('freshness_upper_bound_utc'))
        observation = stamp(quote.get('observed_at_utc'))
        if (not -5 <= (now - proof).total_seconds() <= MAX_AGE
                or proof > observation + timedelta(seconds=5)
                or observation > generated + timedelta(seconds=5)):
            raise AkamaiError('Akamai original source evidence is stale or dated in the future.')
        basis = quote.get('freshness_basis')
        if basis == 'exchange_timestamp':
            if provider not in {'Nobitex', 'Exir'} or stamp(quote.get('exchange_timestamp')) != proof:
                raise AkamaiError('Akamai exchange timestamp provenance differs.')
        elif basis == 'http_cache_checks+observed_book_change':
            if (provider in {'Nobitex', 'Exir'} or quote.get('http_live') is not True
                    or quote.get('exchange_timestamp') is not None):
                raise AkamaiError('Akamai live-book change evidence is missing.')
        else:
            raise AkamaiError('Unsupported Akamai source freshness evidence.')
        if provider == 'Bitpin':
            state, trade = stamp(quote.get('market_state_proof_utc')), stamp(quote.get('latest_trade_utc'))
            if (quote.get('endpoint_selector') != 'bitpin_book'
                    or basis != 'http_cache_checks+observed_book_change'
                    or any(not -5 <= (now - value).total_seconds() <= MAX_AGE for value in (state, trade))
                    or proof > min(state, trade) + timedelta(milliseconds=1)):
                raise AkamaiError('Bitpin original trade/market-state evidence is stale or missing.')
        asks.append(ask); bids.append(bid); proofs.append(proof); observed.append(observation)
    asks.sort()
    with localcontext() as context:
        context.prec = 60
        middle = len(asks) // 2
        median = asks[middle] if len(asks) % 2 else (asks[middle-1] + asks[middle]) / 2
        sides_agree = (len(quotes) >= 2 and all(max(values) <= min(values) * Decimal('1.02')
                                              for values in (asks, bids)))
    expected_ok = len(quotes) >= upstream_minimum and (upstream_minimum == 5 or sides_agree)
    if (evidence.get('ok') is not expected_ok
            or not expected_ok and evidence.get('median_buy_toman') is not None):
        raise AkamaiError('Akamai transaction-quorum envelope disagrees with its source count/agreement policy.')
    if upstream_minimum == 2 and len(quotes) >= 2 and not sides_agree:
        raise AkamaiError('Akamai exchange bids or asks disagree by more than the current 2% policy.')
    if any(not median * Decimal('0.92') <= ask <= median * Decimal('1.08') for ask in asks):
        raise AkamaiError('Akamai source prices exceed the existing median tolerance.')
    if expected_ok and number(evidence.get('median_buy_toman')) != median:
        raise AkamaiError('Akamai original unadjusted median differs from its source quotes.')
    expiry = stamp(evidence.get('valid_until_utc'))
    if not now < expiry <= min(proofs) + timedelta(seconds=MAX_AGE, milliseconds=1):
        raise AkamaiError('Akamai source expiry was reached or extended.')
    return dict(raw_usdt_toman=str(median), rate_source='Market USDT/Toman median ask via Akamai feed: ' + ', '.join(sorted(seen)),
        rate_url=SOURCE, rate_public_url=' | '.join(PROVIDERS[name][1] for name in sorted(seen)),
        rate_caption_fa=('نرخ تقریبی تک‌منبعی؛ در انتظار تأیید منبع دوم؛ ' if len(seen) == 1 else '') +
            'میانه قیمت فروش تتر در دفتر سفارش ' + '، '.join(PROVIDERS[name][0] for name in sorted(seen)),
        rate_observed_at=max(observed).isoformat(), rate_updated_at=min(proofs).isoformat(),
        rate_evidence=evidence)


def read_quote():
    minimum = display_minimum()
    try:
        data = json.loads(regular_bytes(SNAPSHOT, 1024 * 1024))
        if not isinstance(data, dict) or not isinstance(data.get('quotes'), list):
            raise AkamaiError('Invalid Akamai snapshot.')
        evidence = {key: data.get(key) for key in ('schema_version', 'transport', 'ok',
            'generated_at_utc', 'valid_until_utc', 'source_count', 'minimum_sources', 'median_buy_toman')}
        evidence['display_minimum'] = minimum
        evidence['quotes'] = [{key: quote.get(key) for key in QUOTE_FIELDS} for quote in data['quotes']]
        return validate_evidence(evidence, now=datetime.now(timezone.utc), collecting=True)
    except AkamaiError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
        raise AkamaiError('Malformed Akamai market-feed snapshot.') from None

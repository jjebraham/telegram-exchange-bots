"""One auditable USD/market-Toman snapshot, including a 24-hour gainers cover."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import errno
import json
import re
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from crypto_akamai_rate import AkamaiError, AkamaiExpiredError, SOURCE as AKAMAI_SOURCE, read_quote, validate_evidence

TICKERS_URL = 'https://api.coinpaprika.com/v1/tickers?quotes=USD'
STABLE_URL = 'https://api.coinpaprika.com/v1/tags/stablecoin?additional_fields=coins'
WRAPPED_URL = 'https://api.coinpaprika.com/v1/tags/wrapped-token?additional_fields=coins'
MARKET_URL = 'https://api.wallex.ir/v1/markets'
EXIR_URL = 'https://api.exir.io/v2/ticker?symbol=usdt-irt'
NOBITEX_URL = 'https://apiv2.nobitex.ir/v2/trades/USDTIRT'
PRICE_MAX_AGE = 1200  # CoinPaprika's free tickers normally update about every five minutes.
RATE_MAX_AGE = 300
UA = 'KianiExchange-InstagramPrices/1.0'
GAINERS_POLICY = dict(universe='top 100 by USD market capitalization before exclusions',
                      universe_size=100, limit=10, window_hours=24,
                      minimum_volume_usd='50000', volume_comparison='strictly greater',
                      positive_changes_only=True, source='CoinPaprika')

# The tag endpoint omits several established stablecoins and core wrapped assets.
# Explicit IDs prevent that omission from putting these duplicates into the top 50.
PEGGED_IDS = set('''usdt-tether usdc-usd-coin usdc-usdc dai-dai usds-usds
susds-susds usd1-usd1 usde-ethena-usde susde-ethena-staked-usde
usdg-global-dollar pyusd-paypal-usd usdf-falcon-finance usdd-usdd
bfusd-bfusd fdusd-first-digital-usd frax-frax gho-gho
paxg-pax-gold xaut-tether-gold syrupusdc-syrupusdc'''.split())
DUPLICATE_IDS = set('''weth-weth eth-ethereum-token wbtc-wrapped-bitcoin
steth-lido-staked-ether wsteth-wrapped-liquid-staked-ether-20
reth-rocket-pool-eth meth-meth frxeth-frax-ether sfrxeth-staked-frax-ether
oeth-origin-ether'''.split())


class PricesError(RuntimeError):
    pass


class SnapshotExpiredError(PricesError):
    """Retryable only by recollecting and rebuilding before any publish request."""


def provider_label(url):
    parsed = urlsplit(url)
    return (parsed.hostname or 'price provider') + parsed.path


def connection_error(exc):
    """Report useful public-provider diagnostics without proxy URLs or credentials."""
    if isinstance(exc, HTTPError):
        return f'HTTP {exc.code}'
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return f'TLS certificate verification failed, code {reason.verify_code}'
    if isinstance(reason, socket.gaierror):
        return f'DNS lookup failed, code {reason.errno}'
    if isinstance(reason, TimeoutError):
        return 'connection or response timed out'
    if isinstance(reason, ssl.SSLError):
        return f'TLS connection failed ({getattr(reason, "reason", "SSLError")})'
    if isinstance(reason, OSError) and reason.errno:
        return f'network error ({errno.errorcode.get(reason.errno, reason.errno)})'
    if isinstance(exc, json.JSONDecodeError):
        return 'response was not valid JSON'
    return type(reason).__name__


def fetch_json(url, *, attempts=3, timeout=25):
    """Bound response size and retries; credentials are not required by these APIs."""
    for attempt in range(attempts):
        try:
            request = Request(url, headers={'User-Agent': UA, 'Accept': 'application/json',
                                           'Cache-Control': 'no-cache'})
            with urlopen(request, timeout=timeout) as response:
                data = response.read(8_000_001)
            if len(data) > 8_000_000:
                raise PricesError(f'{provider_label(url)} response exceeded the size limit.')
            return json.loads(data, parse_float=Decimal)
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeError) as exc:
            if attempt == attempts - 1:
                raise PricesError(f'{provider_label(url)} unavailable ({connection_error(exc)}); no post created.') from None
            time.sleep(2 * (attempt + 1))


def check_sources():
    """Read-only connectivity check using the publisher's real requests and SSL settings."""
    failed = False
    for url in (STABLE_URL, WRAPPED_URL, TICKERS_URL):
        started = time.monotonic()
        try:
            fetch_json(url, attempts=1, timeout=12)
        except PricesError as exc:
            failed = True
            print(f'FAILED: {exc}', flush=True)
        else:
            print(f'OK: {provider_label(url)} ({time.monotonic() - started:.1f}s)', flush=True)
    try:
        quote = fetch_market_quote()
    except PricesError as exc:
        failed = True
        print(f'FAILED: {exc}', flush=True)
    else:
        print(f"OK: market USDT/Toman | {quote['rate_source']} | "
              f"{round_market_rate(quote['raw_usdt_toman'])} Toman", flush=True)
    print('Connection check complete. Nothing published or scheduled.', flush=True)
    return 1 if failed else 0


def number(value, label, *, positive=False):
    if isinstance(value, bool) or value is None:
        raise PricesError(f'Missing or invalid {label}.')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PricesError(f'Invalid {label}.') from None
    if not result.is_finite() or (positive and result <= 0):
        raise PricesError(f'Invalid {label}.')
    return result


def round_market_rate(value):
    """Round Toman per USDT to the nearest 100; exact half steps round up."""
    raw = number(value, 'raw USDT/Toman market price', positive=True)
    with localcontext() as context:
        context.prec = 60
        rounded = raw.quantize(Decimal('1E2'), rounding=ROUND_HALF_UP).quantize(Decimal(1))
    if rounded <= 0:
        raise PricesError('Rounded USDT/Toman market price must be positive.')
    return rounded


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise PricesError('The price provider returned an invalid update time.') from None


def fresh(value, now, max_age, label):
    source_time = timestamp(value)
    age = (now - source_time).total_seconds()
    if age < -300 or age > max_age:
        raise PricesError(f'{label} is stale or dated in the future '
                          f'(age {age:.0f}s; source UTC {source_time.isoformat()}; '
                          f'observed UTC {now.isoformat()}); no post created.')


def nobitex_trade(payload):
    """Use the latest actual trade, not an order-book refresh or request timestamp."""
    if not isinstance(payload, dict) or payload.get('status') != 'ok':
        raise PricesError('Nobitex returned an unsuccessful trade response.')
    trades = payload.get('trades')
    if not isinstance(trades, list) or not trades or len(trades) > 1000:
        raise PricesError('Nobitex returned no bounded recent-trade list.')
    for trade in trades:
        if (not isinstance(trade, dict) or isinstance(trade.get('time'), bool) or
                not isinstance(trade.get('time'), int) or not 10**12 <= trade['time'] < 10**13):
            raise PricesError('Nobitex trade has no original Unix-millisecond timestamp.')
    latest = max(trades, key=lambda trade: trade['time'])
    rial = number(latest.get('price'), 'Nobitex USDT/Rial trade price', positive=True)
    volume = number(latest.get('volume'), 'Nobitex trade volume', positive=True)
    if rial != rial.to_integral_value():
        raise PricesError('Nobitex USDT/Rial trade price is not integral rial.')
    milliseconds = latest['time']
    updated = datetime.fromtimestamp(milliseconds // 1000, timezone.utc).replace(
        microsecond=(milliseconds % 1000)*1000).isoformat()
    # Nobitex's IRT market API prices are RIAL, as its official API docs specify.
    # This is an exact unit conversion; do not infer the unit from price size.
    with localcontext() as context:
        context.prec = 60
        toman = rial / Decimal(10)
    evidence = dict(symbol='USDTIRT', unit='rial', price=str(rial), volume=str(volume), time=milliseconds)
    return toman, updated, evidence


def parse_market_quote(payload, provider, *, sample=False):
    """Public market quotes; normalize documented units without customer adjustments."""
    now = datetime.now(timezone.utc)
    evidence = None
    if not isinstance(payload, dict):
        raise PricesError(f'{provider} returned an invalid market response.')
    try:
        if provider == 'Wallex':
            if payload.get('success') is False:
                raise PricesError('Wallex returned an unsuccessful market response.')
            raw = payload['result']['symbols']['USDTTMN']['stats']['lastPrice']
            updated = None  # This response does not timestamp the last trade.
            source, url, public_url = 'Wallex USDTTMN last trade', MARKET_URL, 'https://wallex.ir'
            caption = 'آخرین معامله بازار USDTTMN در والکس'
        elif provider == 'Exir':
            if payload.get('symbol', 'usdt-irt') != 'usdt-irt':
                raise PricesError('Exir returned the wrong market pair.')
            raw = payload['last']
            # Exir documents `timestamp` for /ticker, but its current live
            # response also uses the `time` field documented for /tickers.
            # Both are ORIGINAL provider times; retrieval time is not a fallback.
            source_times = [payload[key] for key in ('timestamp', 'time') if key in payload]
            if not source_times:
                raise PricesError('Exir ticker has neither an original timestamp nor time field.')
            parsed_times = [timestamp(value) for value in source_times]
            if any(value != parsed_times[0] for value in parsed_times[1:]):
                raise PricesError('Exir ticker timestamp and time fields disagree.')
            updated = source_times[0]
            timestamp(updated)
            if not sample:
                fresh(updated, now, RATE_MAX_AGE, 'Exir USDT/IRT ticker')
            source, url, public_url = 'Exir USDT/IRT last trade', EXIR_URL, 'https://www.exir.io'
            caption = 'آخرین معامله بازار USDT/IRT در اکسیر'
        elif provider == 'Nobitex':
            raw, updated, evidence = nobitex_trade(payload)
            if not sample:
                fresh(updated, now, RATE_MAX_AGE, 'Nobitex USDT/Rial last trade')
            source, url, public_url = 'Nobitex USDT/IRT last trade (Rial divided by 10)', NOBITEX_URL, 'https://nobitex.ir'
            caption = 'آخرین معامله تتر در نوبیتکس؛ نرخ ریالی تقسیم بر ۱۰'
        else:
            raise PricesError('Unsupported market quote provider.')
    except (KeyError, TypeError):
        raise PricesError(f'{provider} market USDT/Toman quote is unavailable.') from None
    raw_rate = number(raw, provider + ' USDT/Toman market price', positive=True)
    return dict(raw_usdt_toman=str(raw_rate), rate_source=source, rate_url=url,
                rate_public_url=public_url, rate_caption_fa=caption,
                rate_observed_at=now.isoformat(), rate_updated_at=updated, rate_evidence=evidence)


def fetch_market_quote():
    # The existing restricted-SSH Akamai collector already reaches these venues.
    # Consume its local, unadjusted market evidence; do not retry blocked APIs
    # from Google or use customer quotes with Kiani pricing adjustments.
    try:
        quote = read_quote()
    except AkamaiExpiredError as exc:
        raise SnapshotExpiredError(str(exc)) from None
    except AkamaiError as exc:
        raise PricesError(str(exc) + ' No post created.') from None
    print(f"Akamai market feed: {quote['rate_evidence']['source_count']} fresh exchanges; "
          f"median ask {quote['raw_usdt_toman']} Toman; original expiry "
          f"{quote['rate_evidence']['valid_until_utc']}", flush=True)
    return quote


def excluded(coin, stable_ids, wrapped_ids):
    identity, name = coin['id'], coin['name'].lower()
    symbol = coin['symbol'].upper()
    if identity in stable_ids | PEGGED_IDS:
        return True
    # Dollar/euro stablecoins and their yield-bearing receipts have many aliases.
    if ('USD' in symbol or symbol in {'DAI', 'FRAX', 'LUSD', 'GHO', 'MIM', 'EURC', 'EURT', 'PAXG', 'XAUT'}
            or re.search(r'\bstablecoin\b|\bpegged\b|\bglobal dollar\b', name)):
        return True
    if identity in wrapped_ids | DUPLICATE_IDS:
        return True
    return bool(re.search(r'\bwrapped\b|\bstaked\b|\brestaked\b|\bbridged\b|\bbinance-peg\b', name))


def select_coins(tickers, stable_ids, wrapped_ids, rate, now, *, sample=False):
    if not isinstance(tickers, list):
        raise PricesError('CoinPaprika did not return a ticker list.')
    eligible = []
    seen = set()
    for coin in tickers:
        if not isinstance(coin, dict):
            raise PricesError('Invalid ticker entry.')
        rank = coin.get('rank')
        if not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0:
            continue
        if not all(isinstance(coin.get(k), str) and coin[k].strip() for k in ('id', 'name', 'symbol')):
            raise PricesError('A ranked coin has no identity.')
        if coin['id'] in seen:
            raise PricesError('Duplicate coin identity in the provider response.')
        seen.add(coin['id'])
        if excluded(coin, stable_ids, wrapped_ids):
            continue
        quote = coin.get('quotes', {}).get('USD', {})
        cap = number(quote.get('market_cap', 0), coin['id'] + ' market capitalization')
        if cap <= 0:
            if rank <= 100:
                raise PricesError('A leading coin has no market capitalization; ranking is incomplete.')
            continue
        eligible.append((cap, coin))
    # Rank by market capitalization, not a static list or potentially tied rank field.
    eligible.sort(key=lambda pair: (-pair[0], pair[1]['rank'], pair[1]['id']))
    if len(eligible) < 50:
        raise PricesError('Fewer than 50 eligible coins; partial carousels are not published.')
    chosen = []
    for index, (cap, coin) in enumerate(eligible[:50], 1):
        quote = coin['quotes']['USD']
        usd = number(quote.get('price'), coin['id'] + ' USD price', positive=True)
        updated = coin.get('last_updated')
        timestamp(updated)
        if not sample:
            fresh(updated, now, PRICE_MAX_AGE, coin['symbol'] + ' price')
        change = quote.get('percent_change_24h')
        change = number(change, '24-hour change') if change is not None else None
        with localcontext() as context:
            context.prec = 60
            toman = usd * rate
        chosen.append(dict(position=index, provider_rank=coin['rank'], id=coin['id'],
                           name=coin['name'].strip(), symbol=coin['symbol'],
                           usd=str(usd), toman=str(toman), market_cap_usd=str(cap),
                           change_24h=str(change) if change is not None else None,
                           updated_at=updated))
    return chosen


def market_top100(tickers):
    """Choose the global market-cap universe BEFORE removing pegged/duplicate coins."""
    if not isinstance(tickers, list):
        raise PricesError('CoinPaprika did not return a ticker list.')
    ranked, identities = [], set()
    for coin in tickers:
        if not isinstance(coin, dict):
            raise PricesError('Invalid ticker entry in the gainers universe.')
        rank = coin.get('rank')
        if not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0:
            continue
        if not all(isinstance(coin.get(k), str) and coin[k].strip() for k in ('id', 'name', 'symbol')):
            raise PricesError('A ranked coin has no identity.')
        if coin['id'] in identities:
            raise PricesError('Duplicate coin identity in the gainers universe.')
        identities.add(coin['id'])
        cap = number(coin.get('quotes', {}).get('USD', {}).get('market_cap', 0), 'market capitalization')
        if cap <= 0:
            if rank <= 100:
                raise PricesError('A leading coin has no market cap; top 100 universe is incomplete.')
            continue
        ranked.append((cap, coin))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]['rank'], pair[1]['id']))
    if len(ranked) < 100:
        raise PricesError('Fewer than 100 ranked coins; the gainers universe is incomplete.')
    return [coin for _, coin in ranked[:100]]


def gainer_candidates(tickers):
    """Keep original fields for all 100 members, including excluded/non-winning coins."""
    def saved(value):
        return str(value) if isinstance(value, Decimal) else value
    return [dict(id=coin['id'], name=coin['name'], symbol=coin['symbol'], rank=coin['rank'],
                 last_updated=coin.get('last_updated'), quotes={'USD': {
                     field: saved(coin['quotes']['USD'].get(field)) for field in
                     ('market_cap', 'price', 'volume_24h', 'percent_change_24h')}})
            for coin in market_top100(tickers)]


def select_gainers(candidates, stable_ids, wrapped_ids, rate, now, *, sample=False):
    chosen, omitted = [], []
    for market_position, coin in enumerate(market_top100(candidates), 1):
        reason = None
        if excluded(coin, stable_ids, wrapped_ids):
            reason = 'Stable/pegged coin or wrapped/staked duplicate.'
        else:
            try:
                quote = coin['quotes']['USD']
                usd = number(quote.get('price'), coin['id'] + ' USD price', positive=True)
                volume = number(quote.get('volume_24h'), '24-hour USD trading volume', positive=True)
                change = number(quote.get('percent_change_24h'), '24-hour USD price change')
                updated = coin.get('last_updated')
                timestamp(updated)
                if not sample:
                    fresh(updated, now, PRICE_MAX_AGE, coin['symbol'] + ' gainers quote')
                if volume <= Decimal(GAINERS_POLICY['minimum_volume_usd']):
                    reason = '24-hour USD trading volume is not above 50000.'
                elif change <= 0:
                    reason = 'No positive 24-hour USD price change.'
                else:
                    with localcontext() as context:
                        context.prec = 60
                        toman = usd * rate
                    chosen.append(dict(id=coin['id'], name=coin['name'].strip(), symbol=coin['symbol'],
                        provider_rank=coin['rank'], market_position=market_position,
                        usd=str(usd), toman=str(toman), market_cap_usd=str(number(quote['market_cap'], 'market cap', positive=True)),
                        volume_24h_usd=str(volume), change_24h=str(change), updated_at=updated))
            except PricesError as exc:
                reason = str(exc)
        if reason:
            omitted.append(dict(id=coin['id'], reason=reason))
    chosen.sort(key=lambda coin: (-Decimal(coin['change_24h']), -Decimal(coin['market_cap_usd']), coin['id']))
    eligible_count = len(chosen)
    chosen = [dict(position=index, **coin) for index, coin in enumerate(chosen[:10], 1)]
    return chosen, omitted, eligible_count


def build_snapshot(tickers, stable_tag, wrapped_tag, market=None, *, sample=False, market_quote=None):
    now = datetime.now(timezone.utc)
    for tag, label in ((stable_tag, 'stablecoin'), (wrapped_tag, 'wrapped-token')):
        if not isinstance(tag, dict) or tag.get('id') != label or not isinstance(tag.get('coins'), list):
            raise PricesError('Invalid coin classification response.')
        if not all(isinstance(k, str) for k in tag['coins']):
            raise PricesError('Invalid coin classification identities.')
    quote = market_quote if market_quote is not None else parse_market_quote(market, 'Wallex', sample=sample)
    raw_rate = number(quote['raw_usdt_toman'], 'raw USDT/Toman market price', positive=True)
    rate = round_market_rate(raw_rate)
    coins = select_coins(tickers, set(stable_tag['coins']), set(wrapped_tag['coins']), rate, now, sample=sample)
    candidates = gainer_candidates(tickers)
    ids = {coin['id'] for coin in candidates}
    classifications = dict(stablecoin=sorted(ids & set(stable_tag['coins'])),
                           wrapped_token=sorted(ids & set(wrapped_tag['coins'])))
    gainers, omitted, eligible_count = select_gainers(candidates, set(classifications['stablecoin']),
        set(classifications['wrapped_token']), rate, now, sample=sample)
    return dict(schema=3, sample=sample, generated_at=now.isoformat(),
                usdt_toman=str(rate), raw_usdt_toman=str(raw_rate),
                usdt_rounding='nearest 100 Toman, half up',
                rate_source=quote['rate_source'], rate_url=quote['rate_url'],
                rate_public_url=quote['rate_public_url'], rate_caption_fa=quote['rate_caption_fa'],
                rate_observed_at=quote['rate_observed_at'], rate_updated_at=quote['rate_updated_at'],
                rate_evidence=quote.get('rate_evidence'),
                coin_source='CoinPaprika', coin_url=TICKERS_URL,
                exclusions='Stablecoins, asset-pegged coins, wrapped and staked duplicates', coins=coins,
                gainers=gainers, gainers_policy=dict(GAINERS_POLICY), gainers_candidates=candidates,
                gainers_classifications=classifications, gainers_excluded=omitted,
                gainers_eligible_count=eligible_count)


def collect():
    # Classification first, then prices; rendering and publication freshness checks
    # use the age of the actual tickers, not just the age of a downloaded file.
    stable, wrapped = fetch_json(STABLE_URL), fetch_json(WRAPPED_URL)
    tickers = fetch_json(TICKERS_URL)
    market_quote = fetch_market_quote()
    return build_snapshot(tickers, stable, wrapped, market_quote=market_quote)


def validate_snapshot(snapshot, *, publishing=False):
    if snapshot.get('schema') not in {2, 3} or len(snapshot.get('coins', [])) != 50:
        raise PricesError('Expected one snapshot containing exactly 50 coins.')
    if publishing and snapshot.get('schema') != 3:
        raise PricesError('New publications require a verified gainers cover plus 50 prices.')
    if publishing and snapshot.get('sample'):
        raise PricesError('A reference/sample snapshot cannot be published.')
    now = datetime.now(timezone.utc)
    rate = number(snapshot.get('usdt_toman'), 'USDT/Toman market price', positive=True)
    if rate != round_market_rate(snapshot.get('raw_usdt_toman')):
        raise PricesError('USDT/Toman rate must match the market price rounded to the nearest 100 Toman.')
    if snapshot.get('rate_url') == AKAMAI_SOURCE:
        try:
            original = validate_evidence(snapshot.get('rate_evidence'),
                now=now if publishing else timestamp(snapshot['generated_at']))
        except AkamaiExpiredError as exc:
            raise SnapshotExpiredError(str(exc)) from None
        except AkamaiError as exc:
            raise PricesError(str(exc)) from None
        if any(snapshot.get(key) != value for key, value in original.items()):
            raise PricesError('Akamai market median, sources, units or original freshness evidence changed.')
    elif publishing:
        raise PricesError('New publications require the existing Akamai market feed; direct exchange fallback is disabled.')
    if snapshot.get('rate_url') == NOBITEX_URL or str(snapshot.get('rate_source', '')).startswith('Nobitex '):
        evidence = snapshot.get('rate_evidence')
        if (not isinstance(evidence, dict) or evidence.get('symbol') != 'USDTIRT' or evidence.get('unit') != 'rial' or
                snapshot.get('rate_url') != NOBITEX_URL):
            raise PricesError('Nobitex original trade/unit evidence is missing or changed.')
        raw, updated, _ = nobitex_trade(dict(status='ok', trades=[evidence]))
        if raw != number(snapshot['raw_usdt_toman'], 'raw market rate') or timestamp(updated) != timestamp(snapshot['rate_updated_at']):
            raise PricesError('Nobitex Rial/Toman conversion or original trade time changed.')
    if publishing:
        fresh(snapshot['rate_observed_at'], now, RATE_MAX_AGE, 'USDT/Toman quote')
        if snapshot.get('rate_updated_at') is not None:
            fresh(snapshot['rate_updated_at'], now, RATE_MAX_AGE, 'USDT/Toman ticker')
        fresh(snapshot['generated_at'], now, PRICE_MAX_AGE, 'Price snapshot')
    identities = set()
    for position, coin in enumerate(snapshot['coins'], 1):
        if coin['position'] != position or coin['id'] in identities:
            raise PricesError('Invalid top 50 positions or duplicate identities.')
        identities.add(coin['id'])
        usd = number(coin['usd'], 'USD price', positive=True)
        with localcontext() as context:
            context.prec = 60
            expected = usd * rate
        if number(coin['toman'], 'Toman price', positive=True) != expected:
            raise PricesError('Toman conversion does not match the full-precision USD price.')
        if publishing:
            fresh(coin['updated_at'], now, PRICE_MAX_AGE, coin['symbol'] + ' price')
    if snapshot.get('schema') == 3:
        if snapshot.get('gainers_policy') != GAINERS_POLICY or len(snapshot.get('gainers_candidates', [])) != 100:
            raise PricesError('The gainers selection policy or top 100 evidence changed.')
        classifications = snapshot.get('gainers_classifications', {})
        ids = {coin['id'] for coin in snapshot['gainers_candidates']}
        if (set(classifications) != {'stablecoin', 'wrapped_token'} or
                any(not isinstance(values, list) or any(not isinstance(x, str) or x not in ids for x in values)
                    or len(values) != len(set(values)) for values in classifications.values())):
            raise PricesError('Invalid gainers classification evidence.')
        expected, omitted, eligible_count = select_gainers(snapshot['gainers_candidates'],
            set(classifications['stablecoin']), set(classifications['wrapped_token']), rate,
            timestamp(snapshot['generated_at']), sample=bool(snapshot.get('sample')))
        if (snapshot.get('gainers') != expected or snapshot.get('gainers_excluded') != omitted or
                snapshot.get('gainers_eligible_count') != eligible_count):
            raise PricesError('Gainers order, prices or eligible universe do not match the original evidence.')
        if publishing:
            for coin in expected:
                fresh(coin['updated_at'], now, PRICE_MAX_AGE, coin['symbol'] + ' gainers price')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Read-only top 50 price provider diagnostics')
    parser.add_argument('--check-sources', action='store_true', required=True)
    parser.parse_args()
    raise SystemExit(check_sources())

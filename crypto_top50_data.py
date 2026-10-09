"""One auditable USD/market-Toman snapshot for a five-page Instagram carousel."""
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

TICKERS_URL = 'https://api.coinpaprika.com/v1/tickers?quotes=USD'
STABLE_URL = 'https://api.coinpaprika.com/v1/tags/stablecoin?additional_fields=coins'
WRAPPED_URL = 'https://api.coinpaprika.com/v1/tags/wrapped-token?additional_fields=coins'
MARKET_URL = 'https://api.wallex.ir/v1/markets'
EXIR_URL = 'https://api.exir.io/v2/ticker?symbol=usdt-irt'
PRICE_MAX_AGE = 1200  # CoinPaprika's free tickers normally update about every five minutes.
RATE_MAX_AGE = 300
UA = 'KianiExchange-InstagramPrices/1.0'

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
            request = Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
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
        quote = fetch_market_quote(attempts=1, timeout=8)
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
    age = (now - timestamp(value)).total_seconds()
    if age < -300 or age > max_age:
        raise PricesError(f'{label} is stale or dated in the future; no post created.')


def parse_market_quote(payload, provider, *, sample=False):
    """Both supported pairs are Toman per USDT; neither uses customer quotes."""
    now = datetime.now(timezone.utc)
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
            raw, updated = payload['last'], payload['timestamp']
            timestamp(updated)
            if not sample:
                fresh(updated, now, RATE_MAX_AGE, 'Exir USDT/IRT ticker')
            source, url, public_url = 'Exir USDT/IRT last trade', EXIR_URL, 'https://www.exir.io'
            caption = 'آخرین معامله بازار USDT/IRT در اکسیر'
        else:
            raise PricesError('Unsupported market quote provider.')
    except (KeyError, TypeError):
        raise PricesError(f'{provider} market USDT/Toman quote is unavailable.') from None
    raw_rate = number(raw, provider + ' USDT/Toman market price', positive=True)
    return dict(raw_usdt_toman=str(raw_rate), rate_source=source, rate_url=url,
                rate_public_url=public_url, rate_caption_fa=caption,
                rate_observed_at=now.isoformat(), rate_updated_at=updated)


def fetch_market_quote(*, attempts=2, timeout=12):
    # Fail over quickly when Wallex is unreachable from the publishing server.
    # Exir has a documented public USDT/IRT ticker, already quoted in Toman.
    for provider, url in (('Wallex', MARKET_URL), ('Exir', EXIR_URL)):
        try:
            payload = fetch_json(url, attempts=1 if provider == 'Wallex' else attempts,
                                 timeout=min(timeout, 8) if provider == 'Wallex' else timeout)
            return parse_market_quote(payload, provider)
        except PricesError as exc:
            print(f'Market source unavailable: {exc}', flush=True)
    raise PricesError('No valid live market USDT/Toman quote is available; no post created.')


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
    return dict(schema=2, sample=sample, generated_at=now.isoformat(),
                usdt_toman=str(rate), raw_usdt_toman=str(raw_rate),
                usdt_rounding='nearest 100 Toman, half up',
                rate_source=quote['rate_source'], rate_url=quote['rate_url'],
                rate_public_url=quote['rate_public_url'], rate_caption_fa=quote['rate_caption_fa'],
                rate_observed_at=quote['rate_observed_at'], rate_updated_at=quote['rate_updated_at'],
                coin_source='CoinPaprika', coin_url=TICKERS_URL,
                exclusions='Stablecoins, asset-pegged coins, wrapped and staked duplicates', coins=coins)


def collect():
    # Classification first, then prices; rendering and publication freshness checks
    # use the age of the actual tickers, not just the age of a downloaded file.
    stable, wrapped = fetch_json(STABLE_URL), fetch_json(WRAPPED_URL)
    tickers = fetch_json(TICKERS_URL)
    market_quote = fetch_market_quote()
    return build_snapshot(tickers, stable, wrapped, market_quote=market_quote)


def validate_snapshot(snapshot, *, publishing=False):
    if snapshot.get('schema') != 2 or len(snapshot.get('coins', [])) != 50:
        raise PricesError('Expected one snapshot containing exactly 50 coins.')
    if publishing and snapshot.get('sample'):
        raise PricesError('A reference/sample snapshot cannot be published.')
    now = datetime.now(timezone.utc)
    rate = number(snapshot.get('usdt_toman'), 'USDT/Toman market price', positive=True)
    if rate != round_market_rate(snapshot.get('raw_usdt_toman')):
        raise PricesError('USDT/Toman rate must match the market price rounded to the nearest 100 Toman.')
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


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Read-only top 50 price provider diagnostics')
    parser.add_argument('--check-sources', action='store_true', required=True)
    parser.parse_args()
    raise SystemExit(check_sources())

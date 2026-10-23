"""Limited Google-host fallback for fixed public endpoints, with per-host backoff."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

URLS = {
    'nobitex_book': 'https://apiv2.nobitex.ir/v3/orderbook/all',
    'nobitex_stats': 'https://apiv2.nobitex.ir/market/stats?srcCurrency=usdt&dstCurrency=rls',
    'wallex_markets': 'https://api.wallex.ir/v1/markets',
    'wallex_depth': 'https://api.wallex.ir/v1/depth?symbol=USDTTMN',
    'wallex_trades': 'https://api.wallex.ir/v1/trades?symbol=USDTTMN',
    'tabdeal_depth': 'https://api1.tabdeal.org/r/api/v1/depth?symbol=USDTIRT&limit=50',
    'tabdeal_trades': 'https://api1.tabdeal.org/r/api/v1/trades?symbol=USDTIRT&limit=3',
    'ramzinex_book': 'https://publicapi.ramzinex.com/exchange/api/v1.0/exchange/orderbooks/11/buys_sells',
    'ramzinex_pairs': 'https://publicapi.ramzinex.com/exchange/api/v1.0/exchange/pairs',
    'raastin_depth': 'https://api.raastin.com/api/v1/market/depth/USDTIRT/',
    'raastin_state': 'https://api.raastin.com/api/v1/market/symbols/?name=USDTIRT',
    'exir_books': 'https://api.exir.io/v2/orderbooks',
    'exir_book': 'https://api.exir.io/v2/orderbook?symbol=usdt-irt',
    'exir_state': 'https://api.exir.io/v2/constants',
    'bitpin_markets': 'https://api.bitpin.ir/api/v1/mkt/markets/',
    'bitpin_book': 'https://api.bitpin.ir/api/v1/mth/orderbook/USDT_IRT/',
    'bitpin_trades': 'https://api.bitpin.ir/api/v1/mth/matches/USDT_IRT/',
    'btcturk_usdt_try': 'https://api.btcturk.com/api/v2/ticker?pairSymbol=USDTTRY',
}
MAX_BYTES = 4 * 1024 * 1024
_lock = threading.Lock()
_blocked_until = {}


class FallbackUnavailable(RuntimeError):
    pass


def _reject_constant(value):
    raise ValueError('Non-finite JSON constant')


def fetch(selector, timeout=5):
    if selector not in URLS:
        raise ValueError('Unsupported Google fallback endpoint')
    host = urlsplit(URLS[selector]).hostname
    with _lock:
        if time.monotonic() < _blocked_until.get(host, 0):
            raise FallbackUnavailable('Google fallback is cooling down for this host')
    status = ''
    headers = {}
    try:
        with tempfile.TemporaryDirectory(prefix='kiani-google-rates-') as folder:
            body = Path(folder) / 'body.json'
            header = Path(folder) / 'headers'
            limit = max(1, min(float(timeout), 5))
            command = ['/usr/bin/curl', '-4', '--noproxy', '*', '--proto', '=https',
                '--max-redirs', '0', '--connect-timeout', '2', '--max-time', str(limit),
                '--max-filesize', str(MAX_BYTES), '--silent', '--show-error', '--compressed',
                '--header', 'Accept: application/json', '--header', 'Cache-Control: no-cache',
                '--header', 'Pragma: no-cache', '--dump-header', str(header),
                '--output', str(body), '--write-out', '%{http_code}', URLS[selector]]
            result = subprocess.run(command, capture_output=True, text=True, timeout=limit + 2,
                                    env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/nonexistent'})
            status = result.stdout.strip()
            if header.exists() and header.stat().st_size <= 128 * 1024:
                for line in header.read_text(errors='replace').splitlines():
                    if line.startswith('HTTP/'):
                        headers = {}
                    elif ':' in line:
                        name, value = line.split(':', 1)
                        if name.lower() in {'date', 'age', 'cache-control', 'etag', 'last-modified',
                                            'content-type', 'via', 'x-cache', 'cf-cache-status', 'retry-after'}:
                            headers[name.lower()] = value.strip()[:300]
            if result.returncode or status != '200':
                raise FallbackUnavailable(f'Google public endpoint unavailable (HTTP {status or "none"}, exit {result.returncode})')
            if not body.is_file() or body.stat().st_size > MAX_BYTES:
                raise FallbackUnavailable('Google fallback response exceeds size limit')
            data = json.loads(body.read_bytes(), parse_constant=_reject_constant)
            if not isinstance(data, (dict, list)):
                raise ValueError('Google fallback response is not a JSON object or array')
        with _lock:
            _blocked_until.pop(host, None)
        return {'ok': True, 'protocol': 1, 'selector': selector,
                'observed_at_utc': datetime.now(timezone.utc).isoformat(),
                'response_headers': headers, 'data': data,
                'transport_route': 'google-direct-fallback', 'outbound_ip': '34.19.54.235'}
    except (OSError, subprocess.SubprocessError, ValueError, FallbackUnavailable):
        delay = 120
        if status in ('401', '403'):
            delay = 600
        elif status == '429':
            try:
                delay = max(120, min(1800, int(headers.get('retry-after', '120'))))
            except ValueError:
                delay = 600
        with _lock:
            _blocked_until[host] = time.monotonic() + delay
        raise

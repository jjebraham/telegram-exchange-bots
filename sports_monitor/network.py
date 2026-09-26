"""Bounded, throttled GETs. Telegram POSTs deliberately use a different client."""
import time
from urllib.parse import urljoin, urlsplit
import requests


class FetchError(RuntimeError):
    pass


class Client:
    def __init__(self, root, delay=1.0):
        self.host = urlsplit(root).hostname
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'RunDiscountMonitor/1.0', 'Accept-Language': 'tr-TR,tr;q=0.9', 'Cache-Control': 'no-cache'})
        self.delay, self.last_request = delay, 0.0

    def get(self, url):
        for attempt in range(3):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
            try:
                for _ in range(5):
                    parts = urlsplit(url)
                    if parts.scheme != 'https' or parts.hostname != self.host or parts.username or parts.password:
                        raise FetchError('Unexpected storefront redirect')
                    self.last_request = time.monotonic()
                    with self.session.get(url, timeout=(10, 35), allow_redirects=False, stream=True) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            target = urljoin(url, response.headers['Location'])
                            # Some shops normalize www away on their own domain.
                            if urlsplit(target).hostname == self.host.removeprefix('www.'):
                                target = target.replace('https://' + self.host.removeprefix('www.'), 'https://' + self.host, 1)
                            url = target
                            continue
                        if response.status_code == 429 or response.status_code >= 500:
                            if attempt < 2:
                                time.sleep(min(30, int(response.headers.get('Retry-After', 2 ** (attempt + 1)))))
                                break
                        if response.status_code != 200:
                            raise FetchError(f'HTTP {response.status_code}')
                        body = bytearray()
                        for chunk in response.iter_content(65536):
                            body.extend(chunk)
                            if len(body) > 20_000_000:
                                raise FetchError('Response exceeds size limit')
                        return url, bytes(body).decode('utf-8', errors='replace')
                else:
                    raise FetchError('Too many redirects')
            except requests.RequestException:
                if attempt == 2:
                    raise FetchError('Network request failed') from None
                time.sleep(2 ** (attempt + 1))
        raise FetchError('Retry limit reached')

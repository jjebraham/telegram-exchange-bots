from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit


def money(value, *, turkish=False):
    """Return integer kuruş. Locale must be explicit; 1.234 is ambiguous."""
    text = str(value).strip().replace('TL', '').replace('₺', '').replace(' ', '')
    if turkish:
        text = text.replace('.', '').replace(',', '.')
    try:
        number = Decimal(text)
        if not number.is_finite() or number < 0:
            raise ValueError('Invalid price')
        return int((number * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise ValueError('Invalid price') from exc


def canonical(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Expected a direct HTTPS product URL')
    return urlunsplit(('https', parts.netloc.lower(), parts.path.rstrip('/') or '/', '', ''))


def normalize_sizes(values):
    result = set()
    for value in values:
        text = re.sub(r'\s+', ' ', str(value).strip().replace(',', '.'))
        if not text or len(text) > 24:
            raise ValueError('Invalid size label')
        result.add(text)
    return tuple(sorted(result, key=lambda s: (not bool(re.fullmatch(r'\d+(\.\d+)?', s)), float(s) if re.fullmatch(r'\d+(\.\d+)?', s) else s)))


@dataclass(frozen=True)
class Product:
    store: str
    sku: str
    name: str
    original: int
    sale: int
    url: str
    sizes: tuple[str, ...]
    observed_at: int

    def __post_init__(self):
        if not self.name or not self.sku or not (0 < self.sale <= self.original):
            raise ValueError('Missing identity or invalid price range')
        object.__setattr__(self, 'url', canonical(self.url))
        object.__setattr__(self, 'sizes', normalize_sizes(self.sizes))

    @property
    def key(self):
        return f'{self.store}:{self.sku}'

    @property
    def discount(self):
        return Decimal(100) * (self.original - self.sale) / self.original

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps([self.key, self.sale, self.original, self.sizes], ensure_ascii=False).encode()).hexdigest()

    def dumps(self):
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def loads(cls, value):
        return cls(**json.loads(value))


def qualifies(product, historical_low=None, history_count=0):
    if not product.sizes:
        return False
    if product.discount >= 35:
        return True
    # A 25–34% ticket needs evidence: 10% below a prior low, >=3 scans.
    return (product.discount >= 25 and history_count >= 3 and historical_low is not None
            and product.sale * 100 <= historical_low * 90)


def change_reason(current, posted, previous, *, elapsed, restock_seen=False):
    if posted is None:
        return 'new'
    if current.sale * 100 <= posted.sale * 95 and posted.sale - current.sale >= 10000:
        return 'price_drop'
    if elapsed < 86400:
        return None
    if current.sizes and (restock_seen or (previous is not None and not previous.sizes)):
        return 'restock'
    added = set(current.sizes) - set(posted.sizes)
    if len(added) >= 2 or (len(posted.sizes) <= 1 and added):
        return 'sizes'
    return None

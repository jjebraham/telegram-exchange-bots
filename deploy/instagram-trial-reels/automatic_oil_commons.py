"""Find clearly labelled, freely licensed illustrations for Reel topics."""
from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode, urlsplit, unquote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from PIL import Image, ImageOps

API = 'https://commons.wikimedia.org/w/api.php'
UA = 'KianiExchangeInstagramReels/1.0 (https://kiani.exchange)'
LIMIT = 10_000_000
TOPICS = (
    (('chatgpt', 'claude', 'copilot', 'llm', 'ai', 'artificial intelligence',
      'machine learning'), 'artificial intelligence',
     ('artificial intelligence', 'chatgpt', 'claude', 'copilot',
      'language model', 'machine learning')),
    (('midterm', 'midterms', 'election', 'elections', 'ballot', 'ballots', 'voting'),
     'election ballot voting', ('election', 'ballot', 'voting')),
    (('cybersecurity', 'cyber attack', 'cyberattack', 'data breach', 'phishing',
      'ransomware', 'hacker', 'hackers', 'hacked'), 'cybersecurity',
     ('cybersecurity', 'cyber security', 'computer security', 'data breach', 'phishing')),
    (('bitcoin', 'btc'), 'bitcoin cryptocurrency', 'bitcoin'),
    (('ethereum', 'ether', 'eth'), 'ethereum cryptocurrency', 'ethereum'),
    (('tether', 'usdt'), 'tether cryptocurrency', 'tether'),
    (('gold',), 'gold bullion', 'gold'),
    (('silver',), 'silver bullion', 'silver'),
    (('oil', 'brent', 'petroleum', 'wti'), 'oil barrels', 'oil'),
    (('asset management', 'asset-management', 'asset manager', 'wealth management', 'wealth manager',
      'fund management', 'fund manager', 'investment management', 'investment manager', 'portfolio management', 'financial services'),
     'investment management finance', ('finance', 'investment', 'asset management', 'fund management')),
    (('crypto', 'cryptocurrency', 'blockchain'), 'cryptocurrency blockchain', 'cryptocurrency'),
    (('central bank', 'interest rate', 'interest rates', 'monetary policy'),
     'central banking', ('central bank', 'monetary policy', 'interest rate')),
    (('inflation', 'consumer prices'), 'inflation economy', ('inflation', 'consumer price')),
    (('stock market', 'stock exchange', 'stock markets', 'stock exchanges'),
     'stock market', ('stock market', 'stock exchange')),
    (('foreign exchange', 'exchange rate', 'exchange rates', 'forex'),
     'currency exchange', ('currency exchange', 'foreign exchange', 'exchange rate')),
)

# Manually reviewed illustration candidates. The exact source file, licence,
# author and current Commons metadata are rechecked before each use.
CURATED = {
    'artificial intelligence': {
        'File:Artificial Intelligence ( Ai ).jpg': '59aeed8dec2e45016b3f7742cfaa72a30510cd0d',
    },
    'bitcoin cryptocurrency': {
        'File:Digital-bitcoin-logo.png': 'c290a46cf2e8f3b7b2f55ab270371f09afa2cefb',
        'File:Bitcoin Digital Currency Logo.png': '7c72b8b536fe5f3790d47fb49bd1eaefd2bf3383',
        'File:Physical bitcoin simplexe.png': '464fbf42a4049f325e80b2850429abdcefb2ff0a',
    },
    'cybersecurity': {
        'File:Cybersecurity Visuals Challenge 2019 - Rebecca Wang.jpg': '471d10bbe7225545980d672b356bf47d2314e33d',
        'File:Cybersecurity Visuals Challenge 2019 - John Hurley.png': '53c58b47a85d5856dc48f644193274996770bb95',
    },
}
LICENSES = {
    'CC BY 2.0': 'https://creativecommons.org/licenses/by/2.0/',
    'CC BY 3.0': 'https://creativecommons.org/licenses/by/3.0/',
    'CC BY 4.0': 'https://creativecommons.org/licenses/by/4.0/',
    'CC0': 'https://creativecommons.org/publicdomain/zero/1.0/',
    'CC0 1.0': 'https://creativecommons.org/publicdomain/zero/1.0/',
}


def _matching_license_url(name, value):
    """Accept Commons' canonical and translated deed links for known licences."""
    canonical = LICENSES.get(name)
    if not canonical:
        return False
    try:
        actual = urlsplit(value)
        expected = urlsplit(canonical)
        if (actual.scheme not in {'http', 'https'}
                or actual.hostname != 'creativecommons.org'
                or actual.username or actual.password or actual.port is not None
                or actual.query or actual.fragment):
            return False
        base = expected.path.rstrip('/')
        path = actual.path.rstrip('/')
        return path == base or bool(re.fullmatch(
            re.escape(base) + r'/deed(?:\.[a-zA-Z0-9-]+)?', path))
    except ValueError:
        return False


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _read(url, limit, timeout):
    request = Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError('Empty or oversized Wikimedia response')
    return data


def _plain(value):
    value = html.unescape(re.sub(r'<[^>]*>', ' ', str(value)))
    return re.sub(r'\s+', ' ', value).strip()


# Explicit editorial exclusion: laboratory glassware is misleading for oil news.
REJECTED_IMAGE_SHA1 = {'ff6f5f933b4d192d88ad8f5a9570827d27d3dd7a'}


def rejected_image(item):
    if str(item.get('sha1', '')).casefold() in REJECTED_IMAGE_SHA1:
        return True
    for key in ('title', 'source_url', 'url'):
        text = unquote(str(item.get(key, ''))).casefold().replace('_', ' ')
        if 'petroleum sample.jpg' in text:
            return True
    return False


def oil_scene(item):
    """Require visible oil infrastructure, rather than a generic oil keyword."""
    if rejected_image(item):
        return False
    text = _plain(str(item.get('title', '')) + ' ' +
                  str(item.get('description', ''))).casefold().replace('_', ' ')
    if re.search(r'beaker|laborator|glassware|test[ -]tube|flask|bottl|'
                 r'(?:oil|petroleum)[ -]samples?|essential[ -]oil|'
                 r'olive[ -]oil|cooking[ -]oil|cosmetic|sunflower|rapeseed', text):
        return False
    petroleum = re.search(r'\b(?:oil|petroleum|crude|brent|wti)\b', text)
    scene = re.search(r'\b(?:barrels?|drums?|refiner(?:y|ies)|tankers?|'
                      r'pump[ -]?jacks?|oil[ -]rigs?|drilling[ -]rigs?|'
                      r'platforms?|pipelines?|storage[ -]tanks?|tank[ -]farms?)\b', text)
    return bool(petroleum and scene)


def _topic(story):
    title = str(story.get('title_original', '')).casefold()
    try:
        slug = unquote(urlsplit(str(story.get('source_url', ''))).path.rsplit('/', 1)[-1])
    except ValueError:
        slug = ''
    for text in (title, re.sub(r'[^a-z0-9]+', ' ', slug.casefold()[:500])):
        for words, query, keyword in TOPICS:
            if any(re.search(r'(?<![a-z0-9])' + re.escape(word) + r'(?![a-z0-9])', text)
                   for word in words):
                return query, keyword
    return None


def collect(story, output_dir, limit=7, *, seconds=30, _curated_only=False):
    """Return verified illustrations; a failed optional source is non-fatal."""
    topic = _topic(story)
    if not topic or limit <= 0:
        return []
    limit = min(int(limit), 7)
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError('Unsafe illustration output directory')
    deadline = time.monotonic() + min(max(float(seconds), 1), 30)
    selected = []
    visited = set()
    pins = CURATED.get(topic[0], {})
    common = {'action':'query', 'format':'json', 'prop':'imageinfo|categories',
              'cllimit':'max', 'iiprop':'url|extmetadata|mime|size|sha1'}

    def pages_for(params, until):
        remaining = until - time.monotonic()
        if remaining <= 0:
            return []
        data = json.loads(_read(API+'?'+urlencode(params), 2_000_000, min(6, max(1, remaining))))
        if not isinstance(data, dict):
            return []
        continuation = data.get('continue') or {}
        if not isinstance(continuation, dict) or 'clcontinue' in continuation:
            return []
        pages = data.get('query', {}).get('pages', {})
        if not isinstance(pages, dict):
            return []
        return [page for page in pages.values() if isinstance(page, dict)]

    def consume(pages, target_count, until):
        for page in pages:
            if len(selected) >= target_count or time.monotonic() >= until:
                break
            target = None
            try:
                raw_title = page.get('title', '')
                if not isinstance(raw_title, str) or not raw_title.startswith('File:') or raw_title in visited:
                    continue
                visited.add(raw_title)
                cats = [str(v.get('title', '')).casefold() for v in page.get('categories', []) if isinstance(v, dict)]
                if not cats or any(any(flag in name for flag in (
                        'license review needed', 'copyright violation', 'fan art', 'delete requests')) for name in cats):
                    continue
                info = page['imageinfo'][0]
                if raw_title in pins and info.get('sha1') != pins[raw_title]:
                    continue
                meta = info['extmetadata']
                value = lambda key: str(meta.get(key, {}).get('value', '')).strip()
                license_name = _plain(value('LicenseShortName'))
                license_url = LICENSES.get(license_name)
                author = _plain(value('Attribution')) or _plain(value('Artist'))
                description = _plain(value('ImageDescription'))
                title = _plain(raw_title)
                relevant = (title+' '+description).casefold()
                candidate = dict(title=title, description=description,
                                 source_url=info.get('descriptionurl'), url=info.get('url'), sha1=info.get('sha1'))
                if rejected_image(candidate) or (topic[1] == 'oil' and not oil_scene(candidate)):
                    continue
                relevance_terms = topic[1] if isinstance(topic[1], tuple) else (topic[1],)
                if not any(term in relevant for term in relevance_terms):
                    continue
                if (not license_url or not _matching_license_url(license_name, value('LicenseUrl'))
                        or value('Restrictions') or not 1 <= len(author) <= 120
                        or not 1 <= len(title) <= 140
                        or re.search(r'https?://|[\r\n<>]', author)
                        or info.get('mime') not in {'image/jpeg','image/png','image/webp'}
                        or type(info.get('size')) is not int or not 1000 <= info['size'] <= LIMIT
                        or not re.fullmatch(r'[0-9a-f]{40}', str(info.get('sha1','')))):
                    continue
                source_url = str(info.get('descriptionurl',''))
                desc = urlsplit(source_url)
                image_url = str(info.get('url',''))
                image = urlsplit(image_url)
                if (desc.scheme != 'https' or desc.hostname != 'commons.wikimedia.org'
                        or unquote(desc.path).replace('_',' ') != '/wiki/' + raw_title
                        or desc.query or desc.fragment or desc.username or desc.password
                        or image.scheme != 'https' or image.hostname != 'upload.wikimedia.org'
                        or image.username or image.password or image.port not in (None,443)):
                    continue
                remaining = until-time.monotonic()
                if remaining <= 0:
                    break
                raw = _read(image_url, LIMIT, min(6, max(1, remaining)))
                if len(raw) != info['size'] or hashlib.sha1(raw).hexdigest() != info['sha1']:
                    continue
                with Image.open(BytesIO(raw)) as original:
                    if original.width < 256 or original.height < 128 or original.width * original.height > 40_000_000:
                        continue
                    original.verify()
                with Image.open(BytesIO(raw)) as original:
                    clean = ImageOps.exif_transpose(original).convert('RGB')
                    clean.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
                    target = output_dir / ('commons-' + str(len(selected)) + '.jpg')
                    if target.exists() or target.is_symlink():
                        raise ValueError('Illustration destination already exists')
                    clean.save(target, format='JPEG', quality=92)
                    target.chmod(0o600)
                selected.append(dict(path=target, kind='illustrative', author=author, title=title,
                                     license=license_name, license_url=license_url,
                                     source_url=source_url))
            except Exception:
                if target is not None and target.is_file() and not target.is_symlink():
                    target.unlink()

    search_deadline = deadline - min(6.0, max(0, deadline-time.monotonic())/2) if pins else deadline
    if not _curated_only and time.monotonic() < search_deadline:
        try:
            search = dict(common, generator='search', gsrsearch=topic[0],
                          gsrnamespace='6', gsrlimit='15')
            pages = pages_for(search, search_deadline)
            secrets.SystemRandom().shuffle(pages)
            consume(pages, limit, search_deadline)
        except Exception as exc:
            print('Commons image search unavailable:', type(exc).__name__, flush=True)
    if pins and len(selected) < limit and time.monotonic() < deadline:
        try:
            pages = pages_for(dict(common, titles='|'.join(pins)), deadline)
            secrets.SystemRandom().shuffle(pages)
            consume(pages, limit, deadline)
        except Exception as exc:
            print('Curated Commons images unavailable:', type(exc).__name__, flush=True)
    return selected

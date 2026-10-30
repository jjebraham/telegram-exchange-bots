"""Find clearly labelled, freely licensed illustrations for Reel topics."""
from __future__ import annotations

import hashlib
import html
import json
import re
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
    (('bitcoin', 'btc'), 'bitcoin cryptocurrency', 'bitcoin'),
    (('ethereum', 'ether', 'eth'), 'ethereum cryptocurrency', 'ethereum'),
    (('tether', 'usdt'), 'tether cryptocurrency', 'tether'),
    (('gold',), 'gold bullion', 'gold'),
    (('silver',), 'silver bullion', 'silver'),
    (('oil', 'brent'), 'crude oil', 'oil'),
    (('crypto', 'cryptocurrency', 'blockchain'), 'cryptocurrency blockchain', 'cryptocurrency'),
)
LICENSES = {
    'CC BY 4.0': 'https://creativecommons.org/licenses/by/4.0/',
    'CC0': 'https://creativecommons.org/publicdomain/zero/1.0/',
    'CC0 1.0': 'https://creativecommons.org/publicdomain/zero/1.0/',
}


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


def _topic(story):
    title = str(story.get('title_original', '')).casefold()
    for words, query, keyword in TOPICS:
        if any(re.search(r'(?<![a-z0-9])' + re.escape(word) + r'(?![a-z0-9])', title)
               for word in words):
            return query, keyword
    return None


def collect(story, output_dir, limit=7, *, seconds=30):
    """Return verified illustrations; a failed optional source is non-fatal."""
    topic = _topic(story)
    if not topic or limit <= 0:
        return []
    limit = min(int(limit), 7)
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError('Unsafe illustration output directory')
    deadline = time.monotonic() + min(max(float(seconds), 1), 30)
    params = {'action':'query', 'format':'json', 'generator':'search',
              'gsrsearch':topic[0], 'gsrnamespace':'6', 'gsrlimit':'15',
              'prop':'imageinfo|categories', 'cllimit':'max',
              'iiprop':'url|extmetadata|mime|size|sha1'}
    timeout = min(10, max(1, deadline-time.monotonic()))
    data = json.loads(_read(API+'?'+urlencode(params), 2_000_000, timeout))
    # Search continuation is normal; category continuation would leave
    # a candidate's review flags incomplete.
    if not isinstance(data, dict):
        return []
    continuation = data.get('continue') or {}
    if not isinstance(continuation, dict) or 'clcontinue' in continuation:
        return []
    pages = data.get('query', {}).get('pages', {})
    if not isinstance(pages, dict):
        return []
    selected = []
    ordered = sorted(pages.values(), key=lambda p: p.get('index', 999999))
    for page in ordered:
        if len(selected) >= limit or time.monotonic() >= deadline:
            break
        target = None
        try:
            if not isinstance(page, dict) or not str(page.get('title','')).startswith('File:'):
                continue
            cats = [str(v.get('title', '')).casefold() for v in page.get('categories', []) if isinstance(v, dict)]
            if not cats or any(any(flag in name for flag in (
                    'license review needed', 'copyright violation', 'fan art', 'delete requests')) for name in cats):
                continue
            info = page['imageinfo'][0]
            meta = info['extmetadata']
            value = lambda key: str(meta.get(key, {}).get('value', '')).strip()
            license_name = _plain(value('LicenseShortName'))
            license_url = LICENSES.get(license_name)
            author = _plain(value('Artist'))
            requested_credit = _plain(value('Attribution'))
            if requested_credit:
                author = requested_credit
            description = _plain(value('ImageDescription'))
            title = _plain(page['title'])
            relevant = (title+' '+description).casefold()
            if topic[1] not in relevant:
                continue
            if (not license_url or value('LicenseUrl').rstrip('/') != license_url.rstrip('/')
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
                    or unquote(desc.path).replace('_',' ') != '/wiki/' + page['title']
                    or desc.query or desc.fragment or desc.username or desc.password
                    or image.scheme != 'https' or image.hostname != 'upload.wikimedia.org'
                    or image.username or image.password or image.port not in (None,443)):
                continue
            remaining = deadline-time.monotonic()
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
            continue
    return selected


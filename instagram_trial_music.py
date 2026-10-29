"""Fetch a reviewed Commons soundtrack and retain its attribution evidence."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit, unquote
from urllib.request import Request, build_opener, HTTPRedirectHandler

API = 'https://commons.wikimedia.org/w/api.php'
UA = 'KianiExchangeInstagramReels/1.0 (https://kiani.exchange)'
TRACKS = (
    {'title': 'File:Rafael Krux - The Epic 2.ogg', 'name': 'The Epic 2',
     'sha1': '2fe54b6a30343251ad8b79f98cc1a6d82164deb0', 'moods': ('uplifting', 'energetic'),
     'artist': 'Rafael Krux'},
    {'title': 'File:Epic Trailer by Rafael Krux.ogg', 'name': 'Epic Trailer',
     'sha1': '09b2ea708abb01b4a292f50d47f178eb04ac5b79', 'moods': ('tense',),
     'artist': 'Rafael Krux'},
    {'title': 'File:Sascha ende - Epic Intro 2019 (cc by) (Filmmusic).oga',
     'name': 'Epic Intro 2019', 'sha1': '868acd3c3340766f805d5595a1caacae63c352b0',
     'moods': ('energetic', 'uplifting'), 'artist': 'Sascha Ende'},
)
LIMIT = 10 * 1024 * 1024
LICENSE = 'CC BY 4.0'
LICENSE_URL = 'https://creativecommons.org/licenses/by/4.0/'

MOOD_TERMS = {
    'tense': (
        'hack', 'breach', 'exploit', 'fraud', 'scam', 'sanction', 'arrest',
        'charge', 'lawsuit', 'court', 'crime', 'theft', 'stolen', 'attack',
        'ransomware', 'investigation', 'collapse', 'security', 'risk', 'loss',
        'vulnerability', 'هک', 'نفوذ', 'امنیت', 'ریسک', 'زیان', 'کلاهبرداری',
        'تحریم', 'بازداشت', 'اتهام', 'دادگاه', 'سرقت', 'حمله', 'ورشکستگی',
    ),
    'energetic': (
        'bitcoin', 'crypto', 'market', 'stock', 'trading', 'price', 'surge',
        'rally', 'record', 'upgrade', 'launch', 'technology', 'artificial intelligence',
        'investment', 'rates', 'inflation', 'بیت‌کوین', 'بیت کوین', 'بازار',
        'قیمت', 'رشد', 'جهش', 'رکورد', 'ارتقا', 'فناوری', 'هوش مصنوعی',
        'سرمایه‌گذاری', 'نرخ بهره', 'تورم',
    ),
    'uplifting': (
        'adoption', 'partnership', 'approval', 'milestone', 'growth', 'breakthrough',
        'پذیرش', 'همکاری', 'تأیید', 'توسعه', 'پیشرفت', 'رکورد پذیرش',
    ),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _read(url, limit, timeout=15):
    request = Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError('Empty or oversized Wikimedia response')
    return data


def _plain(value):
    return html.unescape(re.sub(r'<[^>]*>', '', str(value))).strip()


def select_order(story, previous=None):
    fields = ('title_original', 'title_fa', 'summary_original', 'summary_fa', 'summary')
    text = ' '.join(str(story.get(key, '')) for key in fields).casefold()
    # Specific risk/legal signals win over generic market terms. Ambiguous
    # stories use rotation so repeated topics do not always get the same cue.
    mood = None
    for candidate in ('tense', 'energetic', 'uplifting'):
        if any(term in text for term in MOOD_TERMS[candidate]):
            mood = candidate
            break
    return sorted(TRACKS, key=lambda item: (
        item['title'] == previous,
        item['moods'].index(mood) if mood in item['moods'] else len(item['moods']),
        item['name'],
    ))


def retrieve_track(track, output):
    query = urlencode({'action': 'query', 'format': 'json', 'prop': 'imageinfo',
        'iiprop': 'url|extmetadata|mime|size|sha1', 'titles': track['title']})
    data = json.loads(_read(API + '?' + query, 1024 * 1024))
    pages = list(data['query']['pages'].values())
    if len(pages) != 1 or pages[0].get('title') != track['title']:
        raise ValueError('Unexpected music record')
    info = pages[0]['imageinfo'][0]
    meta = info['extmetadata']
    value = lambda key: str(meta.get(key, {}).get('value', '')).strip()
    if (info.get('sha1') != track['sha1'] or info.get('mime') != 'application/ogg'
            or not 1000 <= info.get('size', 0) <= LIMIT or info.get('duration', 0) < 60
            or value('LicenseShortName') != LICENSE
            or value('LicenseUrl').rstrip('/') != LICENSE_URL.rstrip('/')
            or _plain(value('Artist')) != track['artist'] or value('Restrictions')):
        raise ValueError('Music license, attribution or file identity did not match')
    url = info['url']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'upload.wikimedia.org' or parsed.username or parsed.password or parsed.port:
        raise ValueError('Unexpected audio host')
    description = urlsplit(info['descriptionurl'])
    if (description.scheme != 'https' or description.hostname != 'commons.wikimedia.org'
            or unquote(description.path).replace('_', ' ') != '/wiki/' + track['title']
            or description.query or description.fragment):
        raise ValueError('Unexpected attribution URL')
    raw = _read(url, LIMIT, timeout=25)
    if len(raw) != info['size'] or hashlib.sha1(raw).hexdigest() != track['sha1'] or not raw.startswith(b'OggS'):
        raise ValueError('Music download failed integrity verification')
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Music destination already exists')
    with output.open('xb') as handle:
        handle.write(raw)
    output.chmod(0o600)
    return {'title': track['title'], 'name': track['name'], 'artist': track['artist'],
        'license': LICENSE, 'license_url': LICENSE_URL,
        'source_url': info['descriptionurl'], 'sha1': track['sha1'], 'moods': list(track['moods']),
        'changes': 'shortened and faded'}


def caption_credit(info):
    return ('Music: ' + info['name'] + ' — ' + info['artist'] + ' (shortened and faded)\n' +
            info['source_url'] + '\nCC BY 4.0: ' + info['license_url'])

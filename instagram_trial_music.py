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
    {'title': 'File:Fantasy Chamber Adventure by Rafael Krux.ogg',
     'name': 'Fantasy Chamber Adventure',
     'sha1': 'e48e720f1ee5f4c0a1271108c8e5179d92f16c28',
     'moods': ('energetic', 'uplifting'), 'artist': 'Rafael Krux'},
    {'title': 'File:The Entertainer by Kevin MacLeod.ogg', 'name': 'The Entertainer',
     'sha1': '45111a083a1d5ea88142e4813a6727320cca5d4f',
     'moods': ('uplifting',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Breaking News 5 by Sascha Ende.ogg', 'name': 'Breaking News 5',
     'sha1': 'eefdd12c493a519bd3f16674dcd0f9650475611f',
     'moods': ('tense',), 'artist': 'Sascha Ende'},
    {'title': 'File:Alexander Nakarada - Winter Night (cc-by) (filmmusic).ogg',
     'name': 'Winter Night',
     'sha1': 'a53fbbd3742f72e0906747e1a7f5036c3e56efe2',
     'moods': ('tense', 'uplifting'), 'artist': 'Alexander Nakarada'},
    {'title': 'File:Wholesome by Kevin MacLeod.ogg', 'name': 'Wholesome',
     'sha1': '26ce5b020ad048a92ad6dca5f1dd10741b1831a8',
     'moods': ('uplifting',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Sneaky Snitch by Kevin MacLeod.ogg', 'name': 'Sneaky Snitch',
     'sha1': 'e30579458cd3d1104484ac49a2fcc478f0388b96',
     'moods': ('tense',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Cheery Monday by Kevin MacLeod.ogg', 'name': 'Cheery Monday',
     'sha1': 'e5dfc8015e9f05f3faa854a5305c94d7c65dd22d',
     'moods': ('uplifting',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:1984 by Frank Schroeter.ogg', 'name': '1984',
     'sha1': '21ebb2f80ffc3700ca5970df67760aedce84171b',
     'moods': ('energetic', 'tense'), 'artist': 'Frank Schroeter'},
    {'title': 'File:Driving to the Night by Frank Schroeter.ogg',
     'name': 'Driving to the Night',
     'sha1': 'c4187b08f23339d6ba638887e4fe55f66b9790a4',
     'moods': ('energetic',), 'artist': 'Frank Schroeter'},
    {'title': 'File:Ancient Rite by Kevin MacLeod.ogg', 'name': 'Ancient Rite',
     'sha1': '2b4a5f8be535e2b0da873f2cc2fdfeec9b8b60ab',
     'moods': ('tense',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:The Descent by Kevin MacLeod.ogg', 'name': 'The Descent',
     'sha1': '6b8bf57de9e9624816686b2f3dde46d62a108f38',
     'moods': ('tense', 'energetic'), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Elf Meditation Preview by Kevin MacLeod.ogg',
     'name': 'Elf Meditation Preview',
     'sha1': '4897c367300021acaff2874c770e80cbda116f7d',
     'moods': ('tense',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Maple Leaf Rag by Kevin MacLeod.ogg', 'name': 'Maple Leaf Rag',
     'sha1': 'a4a0463bc781240933b10a768cbea53286cc548b',
     'moods': ('uplifting',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Strength Of The Titans by Kevin MacLeod.ogg',
     'name': 'Strength Of The Titans',
     'sha1': 'd4b3547e6212cf07311039956871e62a381f8e50',
     'moods': ('energetic',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Journey To The 80s by Frank Schroeter.ogg',
     'name': 'Journey To The 80s',
     'sha1': 'bb65402cba8e270d4314333b48a3a27f43a9fe6a',
     'moods': ('energetic', 'uplifting'), 'artist': 'Frank Schroeter'},
    {'title': 'File:Heavy Trailer 5 by Sascha Ende.ogg', 'name': 'Heavy Trailer 5',
     'sha1': 'b22e4d7fa794a978af4547a615d1e82cba681e3b',
     'moods': ('tense', 'energetic'), 'artist': 'Sascha Ende'},
    {'title': 'File:Frogs Legs Rag by Kevin MacLeod.ogg', 'name': 'Frogs Legs Rag',
     'sha1': '94f37c783eeb19d44a3528ff2ab7e7d7e5cd698b',
     'moods': ('uplifting',), 'artist': 'Kevin MacLeod'},
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
    recent = [previous] if isinstance(previous, str) else list(previous or ())
    recent = [title for title in recent if isinstance(title, str)][:10]
    return sorted(TRACKS, key=lambda item: (
        item['title'] in recent,
        item['moods'].index(mood) if mood in item['moods'] else len(item['moods']),
        -recent.index(item['title']) if item['title'] in recent else 0,
        item['name'],
    ))


def retrieve_track(track, output):
    query = urlencode({'action': 'query', 'format': 'json',
        'prop': 'imageinfo|categories', 'cllimit': 'max',
        'iiprop': 'url|extmetadata|mime|size|sha1', 'titles': track['title']})
    data = json.loads(_read(API + '?' + query, 1024 * 1024))
    pages = list(data['query']['pages'].values())
    if len(pages) != 1 or pages[0].get('title') != track['title']:
        raise ValueError('Unexpected music record')
    categories = [str(item.get('title', '')).casefold()
        for item in pages[0].get('categories', [])]
    if (not categories or any('license review needed' in item or 'fan art' in item
            for item in categories)):
        raise ValueError('Wikimedia Commons license review or fan-art flag is present')
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




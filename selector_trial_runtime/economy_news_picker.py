"""Collect, persist and rank economy news, adapting the user's supplied example."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
import re
import time
from urllib.parse import quote_plus, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from instagram_crypto_news import NewsError, canonical_url

WINDOW = 86400
USER_AGENT = 'KianiExchange-EconomyNews/1.0'


def gnews(query):
    return 'https://news.google.com/rss/search?q=' + quote_plus(query + ' when:1d') + '&hl=en-US&gl=US&ceid=US:en'


FEEDS = [
    ('Google Economy', gnews('economy inflation interest rates')),
    ('Google Central Banks', gnews('"Federal Reserve" OR ECB OR "central bank"')),
    ('Google Jobs', gnews('GDP OR recession OR unemployment OR "jobs report"')),
    ('Google Energy', gnews('"oil prices" OR OPEC')),
    ('Google Trade', gnews('tariffs OR sanctions OR "trade war"')),
    ('Google Markets', gnews('"stock market" OR "bond yields"')),
    ('BBC', 'https://feeds.bbci.co.uk/news/business/rss.xml'),
    ('CNBC', 'https://www.cnbc.com/id/20910258/device/rss/rss.html'),
    ('The Guardian', 'https://www.theguardian.com/business/rss'),
    ('CBC', 'https://www.cbc.ca/webfeed/rss/rss-business'),
    ('NPR', 'https://feeds.npr.org/1006/rss.xml'),
]
SOURCE_WEIGHTS = {
    'reuters': 5, 'bloomberg': 5, 'financial times': 5, 'wall street journal': 5,
    'the economist': 4, 'associated press': 4, 'ap news': 4, 'bbc': 4,
    'the new york times': 4, 'new york times': 4, 'cnbc': 3, "barron's": 3,
    'the guardian': 3, 'al jazeera': 3, 'axios': 3, 'politico': 3,
    'marketwatch': 2, 'yahoo finance': 2, 'fortune': 2, 'business insider': 2,
    'cnn': 2, 'fox business': 2, 'forbes': 1, 'cbc': 3, 'npr': 3,
}
# Group synonyms so 'tariff' and 'tariffs' do not double-count one topic.
TOPICS = (
    (4, r'\bfederal reserve\b|\bfed\b'),
    (4, r'\binterest rates?\b|\brate (?:cut|hike)s?\b'),
    (4, r'\binflation\b|\bcpi\b'), (4, r'\brecession\b|\bgdp\b'),
    (4, r'\bcentral banks?\b|\becb\b|\bimf\b|\bworld bank\b'),
    (4, r'\btariffs?\b|\btrade war\b'), (4, r'\bopec\b|\boil prices?\b'),
    (4, r'\bjobs report\b|\bunemployment\b|\bpayrolls\b'),
    (4, r'\bdebt ceiling\b|\bdefault\b|\bsanctions\b|\bcrash\b|\bcrisis\b|\bshutdown\b'),
    (2, r'\bstocks?\b|\bwall street\b|\bbonds?\b|\byields?\b'),
    (2, r'\b(?:dollar|currenc(?:y|ies)|gold|oil|trade|econom(?:y|ic)|growth|exports|markets)\b'),
)
AUDIENCE = ((3, r'\biran\b|\brial\b'), (2, r'\bturkey\b|\bturkish\b|\blira\b'),
            (1, r'\bgold\b|\bdollar\b|\boil\b'))
PENALTIES = [
    r'\bstocks? to buy\b', r'\bbest\b', r'\bshould you\b', r'\bhow to\b',
    r'\bmortgage rates today\b', r'\bsavings (account|rates)\b', r'\bcd rates\b',
    r'\bopinion\b', r'\bpodcast\b', r'\bquiz\b', r'\bwatch:', r'\bvideo\b',
    r'\bcoupon\b', r'\bhoroscope\b', r'\bmillionaire\b', r'\bretire(?:ment)?\b',
    r'\bsocial security\b',
]
STOPWORDS = set('a an the and or but of to in on for with at by from as is are was were be been it its this that these those after before over under into about amid says said new will would could may might than more most up down out off not no yes how what why who when where which s us u news'.split())


def clean_html(text):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', str(text or '')))).strip()


def source_key(source):
    value = clean_html(source).lower().strip()
    return next((name for name in sorted(SOURCE_WEIGHTS, key=len, reverse=True) if name in value), value)


def source_weight(source):
    return SOURCE_WEIGHTS.get(source_key(source), 1)


def tokenize(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def banks(text):
    names = {'fed': r'\bfed\b|federal reserve', 'ecb': r'\becb\b|european central bank',
             'boe': r'bank of england', 'boj': r'bank of japan', 'tcmb': r'turkish central bank'}
    return {name for name, pattern in names.items() if re.search(pattern, text.lower())}


def same_story(a, b):
    left, right = tokenize(a), tokenize(b)
    if not left or not right:
        return False
    if banks(a) and banks(b) and not banks(a) & banks(b):
        return False
    if left == right:
        return True
    shared = left & right
    return len(shared) >= 3 and len(shared) / min(len(left), len(right)) >= .6 and len(shared) / len(left | right) >= .4


def parse_date(value):
    try:
        date = parsedate_to_datetime(value)
    except (ValueError, TypeError, IndexError):
        try:
            date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError, AttributeError):
            return None
    if date.tzinfo is None:
        return None
    return date.timestamp()


@dataclass
class Item:
    title: str
    link: str
    source: str
    published: float
    summary: str = ''
    image_url: str = ''
    feed_url: str = ''
    id: str = ''


@dataclass
class Story:
    items: list[Item]
    score: float = 0
    breakdown: dict = field(default_factory=dict)

    @property
    def sources(self):
        return {source_key(i.source) for i in self.items}

    @property
    def lead(self):
        return max(self.items, key=lambda i: (source_weight(i.source), i.published, i.link))

    @property
    def newest(self):
        return max(i.published for i in self.items)


def parse_feed(data, feed_url, feed_source, now):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Feed contains unsupported XML declarations')
    root = ET.fromstring(data)
    entries = root.findall('./channel/item')
    if not entries:
        entries = root.findall('{http://www.w3.org/2005/Atom}entry')
    result, seen = [], set()
    for entry in entries[:150]:
        values = {}
        image, link = '', ''
        for node in entry:
            name = node.tag.rsplit('}', 1)[-1]
            value = ''.join(node.itertext()).strip()
            if name in {'title', 'pubDate', 'published', 'description', 'summary', 'source'}:
                values[name] = value
            if name == 'link' and (not node.attrib.get('rel') or node.attrib['rel'] == 'alternate'):
                link = node.attrib.get('href') or value
            if name in {'thumbnail', 'content', 'enclosure'} and node.attrib.get('url'):
                if name != 'enclosure' or node.attrib.get('type', '').startswith('image/'):
                    image = node.attrib['url']
        published = parse_date(values.get('pubDate') or values.get('published'))
        if published is None or not now - WINDOW <= published <= now:
            continue
        try:
            link = canonical_url(link)
        except (ValueError, NewsError):
            continue
        title = clean_html(values.get('title'))
        source = clean_html(values.get('source') or feed_source)
        if title.endswith(' - ' + source):
            title = title[:-len(source)-3].strip()
        # Keep identical headlines from different outlets: coverage is per outlet.
        key = (source_key(source), link)
        if not title or key in seen:
            continue
        seen.add(key)
        result.append(Item(title, link, source, published,
                           clean_html(values.get('description') or values.get('summary')), image, feed_url))
    return result


def fetch_feed(feed, now):
    source, url = feed
    try:
        with urlopen(Request(url, headers={'User-Agent': USER_AGENT}), timeout=15) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError('Feed too large')
        return url, parse_feed(data, url, source, now), None
    except Exception as exc:
        return url, [], type(exc).__name__


def init_storage(con):
    con.executescript('''
        CREATE TABLE IF NOT EXISTS economy_articles (
            id TEXT PRIMARY KEY, source_url TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL, source TEXT NOT NULL, published_at REAL NOT NULL,
            summary TEXT NOT NULL, image_url TEXT NOT NULL, feed_url TEXT NOT NULL,
            first_seen REAL NOT NULL, last_seen REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS economy_articles_fresh ON economy_articles(published_at);
        CREATE TABLE IF NOT EXISTS economy_feed_runs (
            id INTEGER PRIMARY KEY, fetched_at REAL NOT NULL, feed_url TEXT NOT NULL,
            item_count INTEGER NOT NULL, error_type TEXT
        );
        CREATE TABLE IF NOT EXISTS economy_rankings (
            id INTEGER PRIMARY KEY, ranked_at REAL NOT NULL, lead_article_id TEXT NOT NULL,
            article_ids_json TEXT NOT NULL, sources_json TEXT NOT NULL,
            score REAL NOT NULL, breakdown_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS economy_translation_cache (
            input_hash TEXT PRIMARY KEY, model TEXT NOT NULL, title_fa TEXT NOT NULL,
            summary_fa TEXT NOT NULL, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS economy_preparations (
            story_id TEXT PRIMARY KEY, article_titles_json TEXT NOT NULL,
            article_ids_json TEXT NOT NULL, source_text TEXT NOT NULL,
            source_url TEXT NOT NULL, prepared_at REAL NOT NULL
        );
    ''')


def collect(con, feeds=FEEDS, now=None):
    now = time.time() if now is None else now
    init_storage(con)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda feed: fetch_feed(feed, now), feeds))
    total, failed = 0, 0
    with con:
        for url, items, error in results:
            con.execute('INSERT INTO economy_feed_runs(fetched_at,feed_url,item_count,error_type) VALUES (?,?,?,?)',
                        (now, url, len(items), error))
            if error:
                failed += 1
                print(f'Feed unavailable: {urlsplit(url).hostname} ({error})')
            for item in items:
                key = hashlib.sha256(item.link.encode()).hexdigest()[:24]
                con.execute('''INSERT INTO economy_articles VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_url) DO UPDATE SET title=excluded.title,
                    source=excluded.source, summary=excluded.summary,
                    image_url=excluded.image_url, last_seen=excluded.last_seen''',
                    (key, item.link, item.title, item.source, item.published, item.summary,
                     item.image_url, item.feed_url, now, now))
                total += 1
    return {'fresh_items': total, 'feeds': len(feeds), 'failed_feeds': failed}


def score(story, now):
    text = ' '.join(i.title for i in story.items).lower()
    topic = min(10, sum(weight for weight, pattern in TOPICS if re.search(pattern, text)))
    audience = min(4, sum(weight for weight, pattern in AUDIENCE if re.search(pattern, text)))
    age = (now - story.newest) / 3600
    story.breakdown = dict(coverage=3 * min(len(story.sources), 8),
                          authority=max(source_weight(s) for s in story.sources),
                          topic=topic, audience=audience,
                          freshness=3 if age < 6 else 1 if age < 12 else 0,
                          penalty=-8 if any(re.search(p, story.lead.title.lower()) for p in PENALTIES) else 0)
    story.score = sum(story.breakdown.values())
    return story


def economy_relevant(text):
    text = text.lower()
    # Criminal-court sanctions and sports gold medals are not macro economy news.
    strong = r'\b(?:inflation|gdp|recession|unemployment|payrolls|tariffs?|exports|economy|economic|stocks?|bonds?|yields?|opec)\b|federal reserve|\bfed\b|central bank|\becb\b|interest rates?|oil prices?|jobs report|trade war'
    return bool(re.search(strong, text) or
                re.search(r'\b(?:sanctions|gold|dollar|currency|oil|markets?|crash|crisis|shutdown)\b', text)
                and re.search(r'\b(?:bank|financial|finance|trade|price|prices|economic|economy|debt|budget|energy|rally|slump)\b', text))


def blocked_titles(con):
    rows = con.execute('''SELECT e.article_titles_json FROM economy_preparations e
        JOIN instagram_news_publications p ON e.story_id=p.story_id
        WHERE p.status!='failed' ''')
    return [title for row in rows for title in json.loads(row[0])]


def rank(con, now=None):
    now = time.time() if now is None else now
    init_storage(con)
    rows = con.execute('SELECT * FROM economy_articles WHERE published_at BETWEEN ? AND ?',
                       (now - WINDOW, now)).fetchall()
    items = [Item(r['title'], r['source_url'], r['source'], r['published_at'], r['summary'],
                  r['image_url'], r['feed_url'], r['id']) for r in rows]
    stories = []
    for item in sorted(items, key=lambda i: (source_weight(i.source), i.published, i.link), reverse=True):
        for story in stories:
            if same_story(item.title, story.lead.title):
                story.items.append(item)
                break
        else:
            stories.append(Story([item]))
    blocked = blocked_titles(con)
    candidates = []
    with con:
        for story in stories:
            score(story, now)
            # Store all rankings; select economy reporting, excluding tips and opinion.
            con.execute('''INSERT INTO economy_rankings(ranked_at,lead_article_id,
                article_ids_json,sources_json,score,breakdown_json) VALUES (?,?,?,?,?,?)''',
                (now, story.lead.id, json.dumps([i.id for i in story.items]),
                 json.dumps(sorted(story.sources)), story.score, json.dumps(story.breakdown)))
            if not story.breakdown['topic'] or story.breakdown['penalty'] or not economy_relevant(' '.join(i.title for i in story.items)):
                continue
            if any(same_story(i.title, title) for i in story.items for title in blocked):
                continue
            candidates.append(story)
    return sorted(candidates, key=lambda s: (-s.score, -s.newest, s.lead.link))

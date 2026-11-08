from pathlib import Path
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener
import json
import sys

home = Path.home()
config = json.loads((home / '.local/state/kiani-instagram-insights/activation.json').read_text())
runtime = home / 'kiani-instagram-ranked-news-releases' / config['news_runtime_revision']
sys.path[:0] = [str(runtime), str(runtime / 'selector_trial_runtime')]
import instagram_ranked_news as ranked
import crypto_news_trial as engine

ranked.configure_engine('economy')
# Temporary in-memory probe only; the installed allowlist is not modified.
engine.PUBLISHERS['cnbctv18.com'] = 'CNBC TV18'

class Times(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'time' and attrs.get('datetime') and len(self.values) < 8:
            self.values.append(attrs['datetime'][:120])

paths = sorted((home / '.local/state/kiani-instagram-news-ranking/runs').glob('economy-*/ranking.json'),
               key=lambda path: path.stat().st_mtime, reverse=True)[:20]
examples = {'Yahoo Finance': [], 'CNBC TV18': []}
for path in paths:
    if path.stat().st_size > 5_000_000:
        continue
    audit = json.loads(path.read_text())
    for item in audit.get('excluded') or []:
        if not isinstance(item, dict):
            continue
        for attempt in item.get('attempts') or []:
            if not isinstance(attempt, dict):
                continue
            url = attempt.get('resolved_url') or ''
            host = (urlsplit(url).hostname or '').lower()
            key = ('Yahoo Finance' if host == 'finance.yahoo.com' or host.endswith('.finance.yahoo.com') else
                   'CNBC TV18' if host == 'cnbctv18.com' or host.endswith('.cnbctv18.com') else None)
            if key and url not in examples[key] and len(examples[key]) < 2:
                examples[key].append(url)

for label, urls in examples.items():
    print('\n' + label + ' | saved examples:', len(urls))
    for url in urls:
        parts = urlsplit(url)
        print('Article:', urlunsplit((parts.scheme, parts.netloc, parts.path, '', '')))
        try:
            checked = engine.checked_url(url, article=True)
            request = Request(checked, headers={'User-Agent': 'KianiExchange-NewsSelectorTrial/1.0', 'Accept': 'text/html'})
            with build_opener(engine.PublisherRedirects()).open(request, timeout=10) as response:
                final = engine.checked_url(response.geturl(), article=True)
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                print('Result: article exceeds current size limit')
                continue
            text = raw.decode('utf-8', errors='replace')
            dates, article, times = engine.Dates(final), engine.ArticleParser(), Times()
            dates.feed(text)
            article.feed(text)
            times.feed(text)
            print('Final host:', urlsplit(final).hostname)
            print('Existing publication date fields:', dates.dates[:6])
            print('HTML time values (unverified):', times.values)
            print('Article paragraph characters:', sum(len(x) for x in (article.article_parts or article.parts)))
            print('Lead image metadata present:', bool(article.meta.get('og:image') or article.meta.get('twitter:image')))
        except HTTPError as exc:
            print('Source check: HTTP', exc.code)
        except Exception as exc:
            print('Source check:', type(exc).__name__)
print('\nRead-only probe complete. No model or Instagram request was made.')

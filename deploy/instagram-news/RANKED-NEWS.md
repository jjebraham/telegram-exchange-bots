# Two ranked news posts per category daily

## Confirmed schedule (Europe/Istanbul)

| Feed | First | Second | Typical Story previews |
|---|---|---|---|
| Economy | 13:00 | 20:00 | 13:30 and 20:30 |
| Crypto | 18:00 | 21:30 | 18:30 and 22:00 |

Each story is a separate Feed post; a long summary can continue on another slide
in that post. The first slide of each successful post enters the existing delayed
Story queue. Delay is 30 minutes after actual Feed success, not exactly the clock
times above. Existing 11:30 rates, 16:00 top 50 and Story-worker jobs are preserved.

Every slot re-ranks a rolling 24-hour window and excludes previous events. A
second-slot run can catch up two posts if the first run produced none. The cap
is two news stories per category and Istanbul calendar day, including successful
legacy publications and unresolved/in-flight attempts. It never fills a slot
with an under-threshold story just to reach two.

## What the old scores were doing

The audited installed crypto revision adds security40, regulation35, markets25
and industry15 through substring matches, for a maximum115. Mentioning Bitcoin
and security can score even when these are background rather than the main event.
Its 24-hour timestamp was Telegram delivery, rather than original publication.

The audited economy revision adds coverage up to24, authority5, topic10,
audience4 and freshness3. Coverage dominates its maximum46. Syndicated outlets
and lexical headline splits can overstate or split the same event's coverage.

The server supplied SHA256 values for both installed entry points and the economy
picker match those audited source versions. The earlier crypto trial in PR61
was never confirmed deployed; this release does not assume that it was.

## New score: maximum100

| Factor | Maximum | Interpretation |
|---|---:|---|
| Main event impact | 30 | Specific consequence and affected scope |
| Audience relevance | 20 | Useful to ordinary readers; direct Iran/Turkey consequences score higher |
| Reader usefulness | 15 | Understanding changes to money, access, safety or obligations |
| Source evidence | 15 | Reviewed publisher allowlist10; explicit primary-party/document attribution+5 |
| Original source freshness | 10 | Under6h=10; under12h=7; remaining24h=4 |
| Current outlet coverage | 10 | Additional normalized outlets: 0/3/6/9/10 for1/2/3/4/5+outlets |

Minimum55 is an initial editorial threshold, not a learned performance guarantee.
DeepSeek assesses the first three factors and attribution from retrieved source
passages, with discrete numeric bands and validated verbatim evidence quotes.
Its base relevance bands0/5/15/25 are rescaled to0/4/12/20; usefulness0/5/10/20
is rescaled to0/4/8/15. Scores do not depend on keyword counts.

Coverage is a proxy for media attention, not measured Instagram/X audience
popularity. Aliases and duplicated feed links are normalized, but syndicated
reports can still appear under separate outlets. It is capped at10 points;
no independent-reporting claim or fabricated audience impression is made.
The prior screenshots are too small and age-confounded to train these weights.
The existing manual metric-snapshot helper remains available for later24h/48h
evaluation. No unobserved platform metric is scored as zero.

## Eligibility and event handling

- Crypto retains the successful Telegram delivery/translation pool, enriched with
  coverage from six crypto RSS feeds. It does not choose a source story that has
  not entered that Telegram pool.
- Economy discovers through the existing eleven feed configuration. Collection
  continues hourly at minute30 into separate ranking storage.
- Feeds must provide dated items within24h. The final retrieved article must also
  have a timezone-aware original publication timestamp within24h. Source pages,
  original-date metadata and passages are checked; dateModified, date-only and
  Telegram timestamps cannot refresh an old article.
- Lexical discovery groups reduce duplicates. Groups without an eligible source
  from the configured publisher list are recorded and excluded before the source
  shortlist, rather than occupying slots the reader will always reject. The
  source-reading shortlist considers all remaining groups (maximum400) and
  chooses up to40. If fewer than12 original articles can be verified, a second
  pass selects from the remaining groups, within an80-group total reading budget.
  This reserve improves source access; it changes neither the score threshold nor
  the24-hour rule. Twelve is a retrieval target, not a publication requirement.
  The audit preserves all discovered groups, exclusions and both shortlists.
  This is not a claim to assess every global story.
- Up to four source reports per discovery group are tried. Unavailable/unapproved,
  undated or stale articles are excluded. Only the selected source passage is
  assessed for final impact; access failures do not justify inventing facts.
  Known approved sources are tried before unsupported outlets. Attempts record
  resolved URLs, publisher names and HTTP status codes in the private audit.
- A semantic event pass merges wording variants and compares both categories'
  last14days of published events plus all unresolved attempts (maximum160).
  Previously published URLs are excluded across all retained history. A material
  new development can be a new event; repeated background is not.
- Opinion, promotion, broad roundups, unrelated topics, unsupported uncertainty
  and speculative price forecasts are excluded. Official economic reports and
  institutional forecast announcements can be factual hard news.
- Rank by total score, newer verified original source time, then URL. No topic
  quota displaces a higher-ranked distinct qualifying event merely for variety.

Model inputs are untrusted data, not instructions. Quote validation establishes
presence in the supplied passage, not truth or correct interpretation. Full
passages are bounded to6500characters. Semantic judgments require preview review.

### Economy source coverage

The reader includes Euronews, CNA, ABC News (US/Australia), South China Morning
Post, The New York Times and MarketScreener alongside its existing publishers.
TradingView is accepted only for its identified Reuters news URL route, not
community posts or every provider on that platform. Publisher-label aliases such
as Yahoo/Yahoo Finance, WSJ/Wall Street Journal and MarketScreener spelling
variants share one coverage identity. A Google feed label can make a link worth
trying; the resolved publisher hostname/path still must be approved.

Publisher identity references: [Euronews](https://www.euronews.com/about),
[CNA](https://www.channelnewsasia.com/about-us),
[ABC News US](https://abcnews.com/Contact),
[ABC Australia](https://www.abc.net.au/news/about-abc-news),
[SCMP](https://corp.scmp.com/about-us/),
[TradingView Reuters provider](https://www.tradingview.com/news/top-providers/reuters/),
[MarketScreener Reuters report](https://www.marketscreener.com/news/back-to-business-ce7e50dcda8ef422).
These identify sources and distribution routes; membership alone is not a truth
guarantee. Only accessible original passages with a valid original date qualify.
No paywall, subscription or blocked-source access is bypassed.

## Preview, storage and publication safety

`run_ranked_news.py --repo REPO --revision EXACT_SHA` extracts only nine small
source/helper/doc files from Git, never the repository or tracked virtualenv.
It uses the existing Instagram Python environment, font/logo and DeepSeek settings
from `~/sub/.env`. The default previews both categories' top two eligible stories
as up to four separate Feed designs. Source images are used when available;
otherwise the same branded text template is used. Image availability does not
determine importance. Only selected stories are retranslated from original
source passages, with existing factual/number checks.

Private ranking databases and reports are in
`~/.local/state/kiani-instagram-news-ranking/`; preview JPEG links are printed.
Each audit stores the discovery pool, shortlist, source quotes, original dates,
excluded/merged events, components, selected IDs, model/prompt/runtime fingerprints,
preview URLs and, after publication, media IDs. Source passages stay in private
audits and are not placed in public preview manifests.

Publishing preserves the existing crypto/economy publication databases and schema,
so their prior posts and the Story worker remain visible. A durable per-day slot
ledger plus legacy locks and daily caps prevent repeated slot runs and third
posts. Uncertain final publication attempts require review rather than a blind
retry. Partial failures retain successful publication records; later retries
select only remaining quota and unpublished events. A midnight/date change or
source expiry during preparation aborts publication.

## Activation and rollback

After reviewing both categories' exact-runtime previews, run the same launcher
with `--activate`. It requires successful two-story previews for both categories
from the same runtime fingerprint, no older than48h. It verifies the audited
legacy file hashes, publisher owner, private environment file, UTC server,
IstanbulUTC+3 and active cron service. It acquires both legacy publisher locks,
creates a versioned runtime and backs up existing wrappers plus the full crontab.

Only the two news launchers and their recognized cron entries are changed.
Economy collection is preserved; all unrelated jobs and Story state are retained.
Collection uses a separate lock, so its hourly21:30run cannot make the crypto
21:30publication skip due to a shared selection lock.
Manual previews also use their own locks instead of blocking scheduled publishing.
It adds the20:00economy and21:30crypto slots and preserves13:00/18:00. Conflicting
unrecognized commands/timezones or busy publishers stop activation. Activation
publishes nothing immediately. A failed installation restores wrappers and,
when still unchanged by another editor, its prior crontab.

The printed backup contains the two previous wrappers and `crontab.txt`. Restore
them as the original owner only after comparing the current crontab with the
backup so unrelated later changes are preserved. Runtime releases and original
publisher scripts remain available; no broad cleanup or old publisher deletion
is performed. New economy publications also populate the legacy dedup adapter
for a possible rollback.

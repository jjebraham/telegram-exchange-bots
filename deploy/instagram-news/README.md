# Instagram crypto news: manual rollout

This adds a separate news queue and renderer. Existing rate publishing is kept
as installed. The new manual command can publish one image or a carousel of
selected news stories. It uses the existing Instagram credentials and rendering
dependencies, Vazirmatn Regular/Bold and Kiani monogram.

## Existing source and new storage

The live Telegram news publisher stores successful deliveries in
`crypto_news_history.json`. It stores translated Persian titles and summaries in
`translation_cache.json`, keyed by the original title followed by `:` and the
start of the source content. Both files are read only by this importer. Running
the bot module is unnecessary; no Telegram/X calls or translation calls occur.

`--source-dir` points to the directory containing both JSON files.
`--db` points to the new, independent SQLite database. Its two tables hold
imported news and Instagram publication attempts. The default database is under
the current user's `.local/state/kiani-instagram-news` directory.

Automatic selection means **news successfully posted by the Telegram bot during
the last rolling 24 hours**, based on its recorded Unix delivery timestamp.
That timestamp is not represented as the article's publication date. When
available, the article's own date appears on the slide. Future timestamps and
stories outside the delivery window are excluded. Missing cached Persian
translations are reported and skipped.

An editorial ranking heuristic gives security stories 40 points, regulation 35,
major market stories 25 and exchange/banking stories 15, adding matching groups.
Recency breaks equal scores. It is a transparent priority rule, not a model's
claim of objective importance. Scores and matching groups are stored in SQLite.
No additional AI/token use is needed for import, ranking or rendering.

## Manual example

`france-example.json` is the story explicitly requested for the first manual
test. Its original publication date is October 9, 2026. The numbers, summary and
image come from the supplied Cointelegraph story. Its URL is preserved in the
caption and publisher attribution stays on the source illustration.

Manual inputs are tagged separately and are never eligible for automatic
24-hour selection unless that URL is also imported from a successful Telegram
delivery. The renderer preserves all summary text; longer news continues on
additional slides. Article images are cached after the first download. If an
illustration cannot be fetched, the saved Persian text still renders.

Start with `--dry-run --story-json deploy/instagram-news/france-example.json`.
Use `--publisher-root` to point at the installed rate publisher containing the
shared font/logo and Graph API helpers. Add `--publish` for an explicitly
authorized real test. `--dry-run` is the default and never calls Instagram.

Required server environment for publication: `INSTAGRAM_USER_ID`,
`INSTAGRAM_ACCESS_TOKEN`, and `INSTAGRAM_GRAPH_API_VERSION`, already supplied by
the existing private Instagram environment. Do not copy that file into GitHub.

## Next manual run from the real news queue

```bash
python instagram_crypto_news.py \
  --source-dir /path/to/live-news-files \
  --publisher-root /path/to/installed-instagram-publisher \
  --limit 1 --dry-run
```

`--limit 1` chooses the highest-scoring available story. Up to five stories can
be selected; a complete post must still fit Instagram's ten-slide limit and
caption limit. `--url` explicitly chooses an imported article for a manual
test. `--sync-only` imports without rendering. `--status` prints recent news
records and their Instagram status/media IDs.

Publication success is recorded only after Meta returns a media ID. Concurrent
claims are serialized with SQLite transactions. Already published stories and
unresolved attempts cannot be posted again. A timeout after calling
`media_publish` is saved as `needs_review`, because Meta may have published it;
blind retry is blocked. Check Instagram and the saved container before resolving
such an attempt. Failures before that stage remain eligible for retry.

## Validation

Nine unit tests cover source JSON preservation, cache matching for titles with
colons, the 24-hour window, manual metadata, ranking, canonical URL deduplication,
atomic claims, successful publication state and uncertain publication results.
The first example was rendered and visually reviewed at 1080×1350. A real
Instagram news publication remains for the manual Selenium run.

No news schedule is installed by these commands. Choose its daily time after the
manual test is reviewed; the active rate schedule is independent.

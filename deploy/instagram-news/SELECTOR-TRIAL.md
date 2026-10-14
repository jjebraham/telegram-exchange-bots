# Crypto event selector trial

This is a manual preview trial, separate from the existing daily crypto publisher.
It has no publish flag, Meta/X requests, cron installer or live-runtime replacement.
The 18:00 crypto and 13:00 economy publishers retain their installed rules.
Source article/image downloads and DeepSeek requests are made during the trial.
It uses the existing `~/sub/.env` DeepSeek configuration; Instagram credentials
are not loaded. No new package or model account is required.

## Candidate admission

- Import successful Telegram deliveries and their existing Persian translations
  into `~/.local/state/kiani-news-selector-trial/trial.sqlite3`.
- Read the production news database with SQLite `mode=ro`, `query_only=ON`.
  Published and unresolved source URLs are excluded; pre-publication failures
  remain candidates, matching the existing selector's behavior.
- Fetch original publisher passages. Require an explicit timezone-aware original
  publication time within 24 hours. Telegram delivery, date-only strings and
  `dateModified` do not substitute for the original publication time.
- Support publication metadata and Article/NewsArticle JSON-LD; reject missing
  dates, conflicting dates, inaccessible passages and publishers outside the
  explicit code allowlist. A listed publisher is not proof that every claim is true.
- Assess every remaining candidate, not just the existing rule's top choices.
  More than 120 candidates stops the default run rather than silently narrowing
  the pool. The standalone program permits an explicit cap up to 200.

The report shows the existing algorithm's winner before these stricter article
checks, and the proposed ranking after them. This makes an exclusion explainable
instead of claiming that both algorithms necessarily ranked the same pool.

## Proposed scoring: maximum 100

| Factor | Points | Evidence |
|---|---|---|
| Main event impact | 0/5/10/20/30 | Concrete consequence and affected scope |
| Audience relevance | 0/5/15/25 | Crypto holders generally, or direct Iran/Turkey consequences |
| Reader usefulness | 0/5/10/20 | Specific awareness about money, access, safety or obligations |
| Sourcing | 10 or 15 | Listed publisher; +5 for explicit primary-party/document attribution |
| Freshness | 10/7/4 | Source publication under 6h, under 12h, otherwise within 24h |

DeepSeek assesses the first three factors and primary attribution against a
fixed rubric. Numeric bands, coverage of candidate IDs and exact source evidence
quotes are validated. Non-news opinion, promotional copy, predictions and broad
roundups are excluded. Alleged/proposed developments can qualify but retain that
uncertainty. Unknown events do not qualify.

A second bounded JSON assessment groups reports of the same event and compares
them with 30 days of published news plus all unresolved attempts (at most 100
history records, with 500-character titles and 1,000-character summary excerpts).
Repeated
events are excluded unless there is a material new development. Highest score,
then newer original source time, then URL choose each representative and final
order. The default preview threshold is 60; fewer than five eligible distinct
events yields fewer rows, and no story above threshold yields no substitute.

These weights and threshold are an initial editorial proposal. They have not
been validated as predictors of Instagram views. Semantic assessment and event
grouping require human review; quote validation establishes source presence,
not truth, completeness or a correct score. A source passage is truncated to
6,500 characters for bounded assessment. No X/Instagram metric bonus is used.

## Preview and audit

Only the winner is retranslated from the original retrieved passage using the
existing DeepSeek factual/number checks. The event-summary interpretation is
not the translation input. Existing Vazirmatn fonts, Kiani logo and card renderer
are reused. A source picture is used if available, otherwise a text card; a
picture does not determine a story's score. Longer copy can continue on another
slide, following the existing renderer. Translated summary text is not silently
truncated by the renderer.

Unmodified preview helpers are bundled under `selector_trial_runtime/` from the
reviewed economy revision `ed50327ee0bd0082be479606f26648a46e35c636`. Their source
blob hashes are listed in `PINNED.md`. They are used only inside this temporary
trial process; no files are copied into the active publishers.

Private audit/cache and JSON/Markdown reports are stored under:
`~/.local/state/kiani-news-selector-trial/`.
Each run records candidate scores, verbatim quotes, source date evidence,
exclusions, event groups, current-rule winner, selected ID, model/prompt hashes,
translation and preview manifest. Source documents are untrusted model input.

Preview JPEGs are placed in the existing public media tree's `news-trial/`
directory. The printed URLs are previews, not Instagram posts. Keep the full
JSON audit private; paste the console ranking and preview URLs for review.

Run the pinned `run_selector_trial.py --repo REPO --revision EXACT_SHA` helper
with the system Python. It extracts an exact allowlist of nine small trial/helper
files from Git into a private temporary directory and invokes the existing
Instagram virtual environment. It never checks out the full repository or its
tracked virtual environments. It requires at least 64 MiB free on the temporary,
home and preview filesystems to leave room for reports/cache/images. It loads only translation settings,
streams progress to the terminal and `~/kiani-news-selector-trial.log`, and
keeps the small source directory for follow-up review. No deployment or automatic posting
occurs. Actual server candidates and a live model result must be inspected
before scheduling this selector.

### If the server is out of space

`diagnostics/cleanup_obsolete_instagram_trials.py --repo REPO` performs a
read-only inspection of four exact, superseded Instagram test worktrees.
With `--apply`, it removes only eligible targets through Git's ordinary
`worktree remove`, retaining their committed revisions in dedicated recovery
refs. It stops after at least 128 MiB is available. There is no forced removal,
broad `/tmp` cleanup, worktree pruning, publisher/database deletion or
configuration replacement.

Run this helper through `sudo` from the publisher account so it can inspect
process paths, environments, open files and mapped libraries for all users.
It checks path/ownership, exact detached HEAD, tracked/untracked/ignored data,
launchers, service/cron configuration and process references. Environment and
configuration values are never printed. All Git inspections, recovery refs and
removals run as the repository owner. Changes, data other than disposable Python
bytecode, active references or failed inspections cause a target to be retained.
Without `--apply`, no refs or worktrees are changed.

The cleanup helper is extracted separately from the pinned revision with
`git show`; it does not need a checkout or any Python packages. Keep Git's
automatic maintenance disabled for the low-space fetch using the per-command
settings `gc.auto=0` and `maintenance.auto=false`. Once sufficient space is
available, invoke the existing small-file preview launcher as the normal user.

## Record comparable Instagram observations

`diagnostics/record_news_metrics.py --csv OBSERVATIONS.csv` reads known successful
crypto/economy Feed identities and their posting times from production state,
then stores observations in a separate `metrics.sqlite3` under trial state.
It never calls Meta or X. It requires exact counts; rounded screenshot K values
are not accepted. The CSV columns are:

```csv
media_id,observed_at,views,reach,likes,saves,shares,promotion,source
```

Supply an existing successful news Feed media ID, a timezone-aware observation
timestamp (e.g. `2026-10-15T18:00:00+03:00`), the counts actually observed, promotion
as `organic`, `promoted` or `unknown`, and an observation source such as
`Instagram Insights manual`. Leave unavailable counts empty; they remain null.

Observations between 23–25 hours are labelled `24h`; 47–49 hours are labelled
`48h`; other ages remain `other`. Posting timestamp provenance is preserved.
Stories are never pooled with Feed, missing metrics are not zeros, and repeated
identical observations do not overwrite historical observations. Do not average
promoted and organic posts together or claim that later metrics were known at
selection time. X matching/collection remains a later integration after access
and root tweet IDs are available. This trial does not invent X performance.

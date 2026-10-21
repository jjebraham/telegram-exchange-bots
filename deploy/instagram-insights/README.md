# Instagram insights, news batches and the 12-hour retention rule

## Owner's requested policy

- All current automated posts are organic (confirmed by the account owner).
- Publish up to **10 different qualifying news stories in each existing slot**:
  economy 13:00/20:00, crypto 18:00/21:30, Europe/Istanbul.
- At the **12-hour assessment**, keep news with **400 Views or more** and remove
  news below 400. Views, not unique Viewers, is the requested measure.
- Only crypto/economy **Feed news** is eligible. Exchange rates, Iran gold,
  top 50 prices, calendars and all Stories are excluded from deletion.
- **No replacement post is triggered by deletion.** All publishing uses the
  scheduled news slots, fresh-source checks and existing event deduplication.

The rule is an owner-selected experiment. Low exposure is not proof of dislike;
this code does not claim that deleting weak posts increases subsequent reach or
followers. Profile visits, follows and other engagement are recorded separately.
The original 72-hour relative-baseline proposal is retained only as supplementary
analysis; it does not override the owner's explicit 12-hour/400-view policy.

## Read-only access probe first

Default bootstrap mode matches saved publication IDs to the configured account's
own Meta `/media` listing, then queries insights for up to three recent automated
posts across available image/carousel formats. It prints returned metrics and
actual counts, plus the account's live publishing quota. It does not change posts,
schedules or credentials. Private analytics observations are saved separately.

Metrics: `views`, `reach`, `likes`, `comments`, `saved`, `shares`,
`total_interactions`, `profile_visits`, `follows`. Support varies by format/API
version. Unavailable/malformed/unsupported values are null, never zero. Views
are not silently substituted with impressions, and per-post profile activity is
not replaced with account-wide totals. Publishing access does not prove insights
access: at least one real views/reach result is required before installation.

The GET transport uses the existing Facebook Login Graph host/version and bearer
header, refuses redirects, never follows token-bearing pagination URLs and saves
only sanitized numeric error codes/local statuses. Request budgets and cooldowns
protect capacity for the existing publisher. The normal collector is bounded at
100 calls/nine minutes per invocation; high reported usage stops further reads.

## Token permissions: prove, do not try a deletion

Deletion activation additionally requires a read-only audit of the **current**
Page token. `--audit-permissions` prompts for the same Meta App ID and App Secret
locally (hidden secret input), then uses the existing reviewed token setup helper
to inspect that token's validity, app, type, scopes, expiry and account identity.
It does not rotate credentials or delete a test post. The helper's Meta-required
`debug_token` query contains the input token in memory; raw URLs, responses and
secrets are not logged. Redirects are refused. The App Secret is not persisted.

Required grants include `instagram_manage_insights`, `instagram_manage_contents`,
`instagram_basic` and existing `instagram_content_publish`. Missing grants mean
no deletion activation. Reauthorization, if needed, must use the same app/account
and preserve all existing publishing grants. Never paste tokens or App Secrets
into chat. Audit storage contains only a token fingerprint, account/app IDs,
scope names, verification time and expiry.

Primary Meta sources:

- [Media read, insights and deletion operations](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/igmedia.py)
- [Insights metric definitions](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/instagraminsightsresult.py)
- [Media insights reference](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights/)

## Publishing capacity and story reservations

Ten stories in four slots could produce 40 news Feed posts and 40 delayed Stories
per rolling day, plus other posts. Do not hardcode Meta's account quota as 100.

`instagram_news_batch.py` reads `content_publishing_limit` including
`config.quota_total`, `quota_duration` and `quota_usage` from the actual account.
It conservatively reserves 12 units for non-news Feed/Story pairs and budgets two
units for each new news Feed plus its delayed Story. A fair per-slot cap is
`min(10, floor((quota_total - 12) / 8))`: a reported quota of 50 permits at most
four per slot; 100 permits up to ten. This is a conservative planning rule.

Before **each final Feed publish**, the worker rechecks remaining quota and
pending/newly published Feed Story reservations. Insufficient quota or an
unreadable reservation source defers extra news. Deleting an old post is never
assumed to refund quota. The existing Story worker is unchanged and continues its
own quota checks. Exact capacity may be lower than the initial slot cap.

All existing fresh original-source/date/evidence/translation requirements remain
mandatory. Scores still rank importance; ten is a maximum, not a requirement to
fill the batch with weak, duplicate or unsupported news. Different main stories
are required. The source comparison budget is bounded. The 14-day event history
is checked in chunks of 80 reports, with conservative unions of validated event
groups and no dropping of older matches. Deleted news stays in original
publication history, preventing the same story from being posted again.

## Measurements and deletion safeguards

Metadata uses actual Meta publication timestamps and account-owned media IDs,
matched against read-only publisher state and the existing Story registry. The
private database contains cumulative snapshots, actual observation start/end,
API version, metric availability, checkpoints, retention jobs and run health.

| Checkpoint | Observation window after actual publication |
|---|---|
| 2 hours | 2:00 to before 2:30 |
| 12 hours (news only) | 12:00 to before 12:30 |
| 24 hours | 24:00 to before 25:00 |
| 48 hours | 48:00 to before 49:00 |
| 72 hours | 72:00 to before 73:00 |

Queries must start/end inside their window. Counts are queried sequentially, not
as one atomic transaction. Existing posts receive honest current observations;
their historical 12-hour counts cannot be reconstructed. Missing checkpoints
remain missed. Unavailable counts are never classified as poor performance.

Retention begins with posts published **after retention activation**, never a
retroactive cleanup. All of these must pass before DELETE:

1. The post is classified crypto/economy, confirmed by the canonical original
   news publication database, and present in the account's current media listing.
2. The owner has declared organic exposure, the post is not manually protected,
   and the 12-hour assessment window is still open.
3. Current token fingerprint/scopes/expiry match the verified permission proof.
4. Fresh views/reach are valid and consistent; views are below 400 in two
   observations at least 10 minutes apart within the assessment window.
5. An immediate metadata read confirms the exact media ID, account owner, Feed
   type and publication timestamp. A **second fresh Views read** remains below400.
6. The final request state is committed before sending DELETE. Only an explicit
   `success:true` response marks deletion complete.

Any ambiguity, missing data or verification failure keeps the post. An uncertain
or rejected DELETE pauses all further deletions for human reconciliation and is
never blindly retried. Original publication records and dedup history are not
rewritten. No deletion target is accepted from a free-form CLI media argument.

## Installation and private reports

The pinned bootstrap extracts only the small listed files, with no full Git
checkout, new venv or package installation. Analytics uses standard Python3.11;
the news runtime reuses the already deployed dependencies. Default mode is the
read-only probe, `--declare-organic` records the owner's confirmed declaration.
`--audit-permissions` audits the current token. `--preview-news` renders scheduled
news candidates without Meta publication.

Activation requires a successful exact-runtime/account/API/source-configuration
probe within24hours. `--activate --news-batch --news-retention` also requires the
fresh permission proof, known old news launcher/source hashes and the organic
declaration. It creates immutable releases, backs up changed launchers/config,
analytics settings and crontab, checks concurrent edits and uses guarded rollback.
No immediate post is published or deleted during installation.

The collector runs every15minutes at minutes07/22/37/52. Existing four news slot
times and all rate/calendar/Story schedules stay in place. New batch launchers
use the new immutable news runtime; old release files remain recoverable.

Private database: `~/.local/state/kiani-instagram-insights/insights.sqlite3`.
Log: `~/kiani-instagram-insights-cron.log`.
Private reports under `~/.local/state/kiani-instagram-insights/reports/`:

- `latest.html`: category-filtered report, with actual observed age and retention status.
- `latest.json`: policy, run health, metrics, checkpoints and retention evidence.
- `latest.csv`: latest post-level metrics; unavailable counts are empty cells.
- `checkpoints.csv`: all checkpoint observations and explicit missed states.

Reports stay outside public media directories. HTML is escaped and CSV text is
neutralized against spreadsheet formula execution. Retention/analytics history
is saved even when the underlying Instagram news post is deleted.

```bash
~/collect-kiani-instagram-insights.sh report
~/collect-kiani-instagram-insights.sh probe
~/collect-kiani-instagram-insights.sh keep MEDIA_ID
~/collect-kiani-instagram-insights.sh promoted MEDIA_ID
tail -n 40 ~/kiani-instagram-insights-cron.log
```

`keep` and `promoted` only change private analytics labels; they do not delete
content. A post marked to keep cannot be removed by the policy. If posts are
boosted later, mark them as promoted so organic comparisons remain meaningful.

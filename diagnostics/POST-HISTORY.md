# Read-only Instagram and X history audit

Run `instagram_post_audit.py --days 14` as the existing publisher user.
No extra Python packages or private environment loading are required.

The helper opens the existing publication databases with SQLite `mode=ro`
and `query_only=ON`. It reads the latest rates Feed state and the delayed
Story database. It reports successful Feed media IDs, titles, source article
URLs, scores, slide counts and posting timestamps in Europe/Istanbul.
Multiple stories in one carousel are grouped by Feed media ID.

Feed timestamps saved from Meta by the Story worker take precedence over
local timestamps. A database success timestamp is the time a successful
publish response was recorded. The rates state timestamp is captured during
rendering, so it is labelled approximate when no saved Meta time is available.
Earlier rates dates are recovered only if saved by the Story worker; baseline
records without a timestamp are counted separately. A render manifest alone
is not evidence that a post was published. Failed and uncertain attempts are
not counted as published.

Successful Stories are reported separately with their own media ID and parent
Feed ID. This allows matching designs that appear twice in Content Insights
without merging their metrics.

The X storage check parses the live news bot's source with `ast` and examines
only X-related field names in the Telegram history. It does not import the
bot, execute its code, read environment files, print credential assignments,
start publishers or call either platform API. The reported direct storage
calls are a structural diagnostic, not a guarantee that no other code or log
file saves tweet IDs.

An optional `--csv NEW_REPORT_PATH` saves this report to a new file for joining
with analytics exports; existing destinations are refused. Without that flag,
the helper prints to the terminal and changes no publisher files, databases,
publication state or schedules.

## Comparing performance across platforms

Match the source article URL, event and full headline, not just a broad topic.
Keep tweet IDs, thread-root IDs, Instagram media IDs and timestamps. Treat a
bot's continuation reply separately from audience replies. Compare impressions
at similar post ages and separate organic/promoted and Feed/Story results.

X performance can be a bounded additional signal after factual freshness,
credibility and audience relevance checks. Unmatched stories and stories not
posted on X have missing X evidence, rather than zero impressions. Results
from small audiences should not dominate the selector. Validate whether X
performance predicts Instagram performance on matched stories before assigning
it substantial weight.

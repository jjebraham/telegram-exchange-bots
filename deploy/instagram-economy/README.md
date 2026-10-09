# Daily Kiani economy news

This adapts the supplied `economy_news_picker.py` into a persistent economy news
pipeline. The economy database, public media folder, process lock and cron log
are separate from the deployed rate and crypto news publishers.

## Collection, ranking and source material

Eleven feeds are configured: six Google News economy queries plus BBC business,
CNBC economy, Guardian business, CBC business and NPR business. RSS and Atom are
parsed with the standard library; no additional packages are required beyond the
installed Persian image dependencies. Feed requests have time and size limits.
Individual feed failures are logged, and fresh previously stored articles remain
available. Collection never translates or calls Instagram.

Only items with an explicit, timezone-aware publication date in the rolling last
24 hours are admitted. Missing dates, future dates and update-only Atom entries
are skipped. Refreshing a URL does not reset its stored publication timestamp.
The publisher's own original date is checked again when available. Freshness is
checked immediately before publication.

Similar headlines are grouped conservatively. Identical headlines from distinct
outlets retain separate coverage; repeat appearances of one outlet do not
inflate coverage. Lead headlines are matched rather than chaining every similar
headline into one group. Clearly different central banks are kept separate.

The stored score has six components adapted from the example:

| Component | Rule |
| --- | --- |
| Coverage | 3 points per distinct outlet, capped at 8 outlets |
| Authority | Highest configured source weight, from 1 to 5 |
| Macro topic | Grouped economic topic weights, capped at 10 |
| Audience | Iran, Turkey, currencies, gold and oil; capped at 4 |
| Freshness | 3 points under 6 hours, 1 under 12 hours |
| Penalty | Personal finance tips, opinion and promotional headlines are excluded |

Stories without economic relevance are excluded, including criminal-court
sanctions without economic context. Scores, components, group members and
outlets are saved for inspection. This is an explicit editorial ranking rule,
not an objective guarantee that one story is the most important worldwide.

Google discovery links are resolved to original publisher URLs with the public
article signature/RPC protocol documented by the project credited in `NOTICE`.
If resolution fails, direct publisher feeds remain available. Only the selected
group is inspected for article content and pictures, trying at most four sources
per group. Direct publisher links are preferred. If no usable article and image
is available, the next ranked group is tried and the omission reason is logged.
At most ten groups are attempted. Google link-list summaries are never used as
the article text. Headlines with a source picture are required for economy posts.

## Persian copy and images

Only the selected accessible report is translated with the existing DeepSeek
key. `--translation-env` reads `DEEPSEEK_API_KEY` and optional `DEEPSEEK_MODEL`
from a local env file without executing it or importing a live bot. Existing
process environment values take precedence. Keys are never saved in the news
database, manifests or repository. The default model is `deepseek-flash` as
documented in the provider's current [JSON output example](https://api-docs.deepseek.com/guides/json_mode/).

The prompt treats article text as untrusted data and requests factual Persian
copy without invented context, numerical conversions, advice or added links.
Persian text, JSON structure, length and numerical values are checked. Numbers
not found in the supplied source are rejected. Translation cache keys include
source text, model and prompt version. These checks cannot prove every sentence
is a correct translation; the real manual post should be reviewed before daily
activation. Live DeepSeek integration is checked during that server test.

The existing 1080×1350 news layout is reused with the Kiani monogram, Vazirmatn
fonts and `خبر اقتصادی` badge. The original source illustration and attribution
are preserved. Longer summaries continue on additional slides. The caption
includes the source link and economy branding.

## Database and duplicate prevention

The default SQLite database is
`~/.local/state/kiani-instagram-economy/economy.sqlite3`. It stores source articles,
feed run outcomes, ranking snapshots, translation cache and preparation/source
records. The shared news publication tables record attempts and Meta media IDs.

Previously published and unresolved stories are excluded, including equivalent
headlines from another outlet. A process lock serializes collection, manual
tests and scheduled runs using the same database. Publication success is saved
only after a media ID is returned. An uncertain result after `media_publish` is
marked `needs_review`; blind repeat publication is blocked. Failed attempts
before that point remain retryable.

## Manual checks

Use the existing Instagram Python environment and installed publisher assets.
The CLI defaults to a preview. Examples:

```bash
python instagram_economy_news.py --collect-only
python instagram_economy_news.py --no-fetch --candidates
python instagram_economy_news.py --translation-env /path/to/translation.env \
  --publisher-root /path/to/installed-instagram-publisher --dry-run
```

For the authorized manual Instagram test, load the existing private Instagram
environment and replace `--dry-run` with `--publish`. Create the public economy
folder as a web-readable directory writable by the publisher user. Public base
and output paths can be overridden with `--public-base` and `--output`.

## Activation after manual review

`activate_economy_cron.py` is prepared for later activation. It requires:

- `--revision`: the exact Git SHA used by the successful manual test.
- `--approved-media-id`: that test's Instagram media ID, after reviewing its post.
- `--at`: the requested daily Istanbul time in HH:MM format.
- `--repo`: the local Git repository containing that revision.

The helper checks the publication record and a fingerprint of the five runtime
modules against the chosen revision, so untested changed code is not silently
activated. It installs the tested files permanently, backs up any previous
economy files and the user crontab, and verifies the resulting schedule. It adds
hourly collection and one daily post, preserving other jobs. Collection is
scheduled 30 minutes apart from the daily posting minute to avoid a lock clash.

Activation expects the existing UTC server timezone and converts the requested
Istanbul time using system timezone data. The wrapper reads the existing local
Instagram/translation settings, uses web-readable image permissions and logs
outcomes to a separate economy cron log. No immediate post is made by activation.

Daily activation remains pending the user's manual post review and chosen time.

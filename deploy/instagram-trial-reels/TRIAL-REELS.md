# Kiani Instagram Trial Reels

## Motion, editorial policy and DeepSeek cost notifications

The Trial Reel renderer reveals Persian text word by word and mixes synthesized typing sounds with the already reviewed music. When the article identifies an image on a host belonging to the reviewed publisher, the renderer retrieves the main image and places it above the headline; if an identified image cannot be safely retrieved, the Reel is not published. A missing article image falls back to approved illustrative media or a text cover. Publisher and article URL are added to the caption; source attribution alone does not establish image reuse rights. External CDN hosts require separate review.

The Trial-only selector can include opinions, forecasts, roundups and promotional material. Forecast and promotional labels are displayed; ordinary Feed selection still uses its original criteria. Admin submissions do not require a publication timestamp or a 24-hour age check; unknown time is stored as zero, not as an invented publication time. Automatic selection remains fresh. Reviewed publisher, readable article text, duplicate Trial Reel and Meta quota checks still apply. Up to five admin and five automatic Reels per Istanbul day are allowed independently.

The private bot sends configured admins an estimated DeepSeek cost range after an automatic or manual Trial Reel preparation attempt. It counts the model calls made during that attempt, including retries; a failed or missing usage response is reported as unknown. Previously cached material has no new API charge. Prices use the DeepSeek Flash peak/off-peak rates published on 2026-10-29 and expire 2026-11-29 UTC; after that estimates are unknown until updated. Amounts exclude server and other provider costs. The notice is not a final invoice, and a prepared Reel is not necessarily published. The private `report_reel_usage.py` script provides individual request counts.

This add-on schedules automatic Trial Reels at 11:00, 13:00, 15:00, 17:00 and 20:30 Istanbul. At each slot it ranks eligible crypto and economy news from the preceding 24 hours and selects a distinct story. The existing private Telegram news bot also accepts an administrator-only `/trial <URL>` command.

## Admin use

- Send `/trial https://publisher.example/article` in a private chat with the configured Telegram bot.
- Optional text beside the one link is accepted but ignored by the content renderer; the publisher article is the source of truth.
- A bare URL remains an ordinary Instagram Feed-news request.
- Admin `/trial` links require a readable passage from the reviewed publisher list and a Persian translation. A missing or old publication timestamp does not block them; tweets, Reddit posts and unreviewed publishers remain excluded. Automatic selection applies freshness checks and can include multiple story types.

## Publishing and safeguards

- Automatic selection runs at 20:30 `Europe/Istanbul`; it does not run immediately during installation.
- Up to five admin Trial Reels and five automatic Trial Reels may be reserved per Istanbul calendar day, subject to Meta quota and existing Story reservations. Published, in-progress and unresolved attempts count; definite failures do not. Each automatic slot is attempted at most once, starts within ten minutes of its schedule, and is not backfilled.
- The video is published with `share_to_feed=false` so it stays out of the normal feed while Instagram tests it with non-followers.
- Reels are created with `media_type=REELS` and `trial_params.graduation_strategy=SS_PERFORMANCE`. Instagram, not this publisher, decides whether and when a Trial Reel is shared with followers. Meta does not expose a numeric auto-graduation threshold to this system.
- A rejected/uncertain Meta response never falls back to an ordinary Reel. An uncertain publish is held for review and reserves that day's slot.
- The Reel contains branded motion cards, the Persian title/summary, and an article image when available from a reviewed publisher host. Full summary text is retained; if it cannot fit the reviewed layout, creation is skipped.
- Soundtracks are selected from a curated 20-track Wikimedia Commons pool to match the story's tense, energetic or uplifting tone, while avoiding recent repeats when possible. Each track has a pinned SHA-1; before use the system checks the live license, credited artist, file type, size and duration, confirms its downloaded hash, and rejects Commons files marked for license review or fan art. All 20 tracks are CC BY 4.0, so the caption credits the artist and track, links the source and license, and notes that the music was shortened and faded. Source metadata is stored with the private Reel record. If a music check fails, the existing synthesized typing sound remains as fallback.
- Trial Reel records live in a separate private database. The normal two-hour/200-view Feed-news deletion worker and delayed-Story worker do not process them. Their article URL and event are added to ordinary news deduplication history.
- Container status is checked by the existing private Telegram worker. Publishing is sent only after Meta reports `FINISHED` and the current quota/Story reservation guard passes.

## Install

Prepare the pinned runtime first and review the extracted revision. Then install with `--install`. Installation reuses the existing Telegram bot token and private admin list; it requests no new credentials and publishes nothing. It requires the existing publisher account, Kiani logo/fonts, Pillow with Arabic shaping support, FFmpeg/ffprobe, the active news quota guard, and the current public HTTPS media directory.

The automatic candidate selector can spend the normal source collection and DeepSeek assessment calls at 20:30. If no eligible current story qualifies, it records a no-candidate result and skips that day. A failed video render or unsupported Trial Reel API response also results in no publication.

## Known platform limitation

`SS_PERFORMANCE` requests Instagram's automatic graduation behavior. It is not a promise of follower distribution or reach. Meta's Trial Reels explanation says Instagram bases its automatic decision on views during the first 72 hours; the account's API access/eligibility is ultimately confirmed only when Meta accepts the first Trial Reel container.

References: [Meta Trial Reels announcement](https://about.fb.com/news/2024/12/trial-reels-try-content-non-followers-first-see-what-perfoms-best/) and [Instagram Content Publishing API guide](https://developers.facebook.com/docs/instagram-platform/content-publishing/).

# Direct Reels

The private admin bot also supports `/reel <article URL>`. It uses the same
reviewed publisher/source boundary, Persian translation, animated layout,
publisher image, music selection, public HTTPS asset checks and Meta container
polling as `/trial`, but publishes a normal follower-facing Reel
(`share_to_feed=true`, with no Trial graduation parameters).

Direct-Reel limits are independent of Trial-Reel limits: at most 10 admin
direct Reels and 2 automatically selected direct Reels per Istanbul day. The
automatic slots are 12:00 and 18:00 Europe/Istanbul. Missed slots do not catch
up. Both modes still obey the live Meta publishing quota and protected Story
reservations.

Only direct Reels published after the direct-retention activation cutoff are
eligible for review. At two hours, the worker reads the Reel's Views. At or
above 200 Views it keeps the Reel. Below 200, it requires a second fresh low
reading at least ten minutes later, verifies the same Reel is still owned by
the configured account, checks the current token's verified insights and
content-management permissions, and performs a final fresh Views check. The
bounded assessment window closes 30 minutes after the two-hour point. Missing
metrics, expired windows, API pressure, uncertain ownership, or missing
permission evidence means keep or defer; no blind delete retry or replacement
post is made. Any uncertain delete response pauses direct-Reel deletion for
manual review.

Trial Reels remain outside this direct-Reel deletion policy. Existing ordinary
news-retention decisions and all protected rates, gold, calendars, price
carousels and Stories remain governed by their own existing rules.

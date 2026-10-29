# Kiani Instagram Trial Reels

## Motion, editorial policy and DeepSeek cost notifications

The Trial Reel renderer reveals Persian text word by word and mixes synthesized typing sounds with the already reviewed music. Approved illustrative media can be configured separately under the private `approved-media` directory; no external images are installed by this update. Without a matching approved image, it renders the text cover. Visual assets require explicit review and appropriate licenses before use.

The Trial-only selector can include opinions, forecasts, roundups and promotional material. Forecast and promotional labels are displayed; ordinary Feed selection still uses its original criteria. Admin submissions do not require a publication timestamp or a 24-hour age check; unknown time is stored as zero, not as an invented publication time. Automatic selection remains fresh. Reviewed publisher, readable article text, duplicate Trial Reel and Meta quota checks still apply. Up to five admin Reels per Istanbul day are allowed, separately from one automatic Reel.

The private bot sends configured admins an estimated DeepSeek cost range after an automatic or manual Trial Reel preparation attempt. It counts the model calls made during that attempt, including retries; a failed or missing usage response is reported as unknown. Previously cached material has no new API charge. Prices use the DeepSeek Flash peak/off-peak rates published on 2026-10-29 and expire 2026-11-29 UTC; after that estimates are unknown until updated. Amounts exclude server and other provider costs. The notice is not a final invoice, and a prepared Reel is not necessarily published. The private `report_reel_usage.py` script provides individual request counts.

This add-on creates one original Persian text-card Reel each Istanbul day. At 20:30, it ranks the eligible crypto and economy news collected in the preceding 24 hours and selects the highest-scoring distinct story. The existing private Telegram news bot also accepts an administrator-only `/trial <URL>` command.

## Admin use

- Send `/trial https://publisher.example/article` in a private chat with the configured Telegram bot.
- Optional text beside the one link is accepted but ignored by the content renderer; the publisher article is the source of truth.
- A bare URL remains an ordinary Instagram Feed-news request.
- Admin `/trial` links require a readable passage from the reviewed publisher list and a Persian translation. A missing or old publication timestamp does not block them; tweets, Reddit posts and unreviewed publishers remain excluded. Automatic selection applies freshness checks and can include multiple story types.

## Publishing and safeguards

- Automatic selection runs at 20:30 `Europe/Istanbul`; it does not run immediately during installation.
- Up to five admin Trial Reels and one automatic Trial Reel may be reserved per Istanbul calendar day, subject to Meta quota and existing Story reservations. Published, in-progress and unresolved attempts count; definite failures do not.
- The video is published with `share_to_feed=false` so it stays out of the normal feed while Instagram tests it with non-followers.
- Reels are created with `media_type=REELS` and `trial_params.graduation_strategy=SS_PERFORMANCE`. Instagram, not this publisher, decides whether and when a Trial Reel is shared with followers. Meta does not expose a numeric auto-graduation threshold to this system.
- A rejected/uncertain Meta response never falls back to an ordinary Reel. An uncertain publish is held for review and reserves that day's slot.
- The Reel contains original branded motion cards and the verified Persian title/summary. It does not copy a publisher photo. Full summary text is retained; if it cannot fit the reviewed layout, creation is skipped.
- Soundtracks are selected from two reviewed Wikimedia Commons recordings by Rafael Krux. For each run, the API must return the expected creator, CC BY 4.0 license, identity hash, file type and size; the downloaded audio must match its pinned hash. The Reel caption credits the track, links its source and license, and indicates that it was shortened and faded. Source metadata is stored alongside the private publication record. If music is unavailable, the locally synthesized typing sound remains.
- Trial Reel records live in a separate private database. The normal two-hour/200-view Feed-news deletion worker and delayed-Story worker do not process them. Their article URL and event are added to ordinary news deduplication history.
- Container status is checked by the existing private Telegram worker. Publishing is sent only after Meta reports `FINISHED` and the current quota/Story reservation guard passes.

## Install

Prepare the pinned runtime first and review the extracted revision. Then install with `--install`. Installation reuses the existing Telegram bot token and private admin list; it requests no new credentials and publishes nothing. It requires the existing publisher account, Kiani logo/fonts, Pillow with Arabic shaping support, FFmpeg/ffprobe, the active news quota guard, and the current public HTTPS media directory.

The automatic candidate selector can spend the normal source collection and DeepSeek assessment calls at 20:30. If no eligible current story qualifies, it records a no-candidate result and skips that day. A failed video render or unsupported Trial Reel API response also results in no publication.

## Known platform limitation

`SS_PERFORMANCE` requests Instagram's automatic graduation behavior. It is not a promise of follower distribution or reach. Meta's Trial Reels explanation says Instagram bases its automatic decision on views during the first 72 hours; the account's API access/eligibility is ultimately confirmed only when Meta accepts the first Trial Reel container.

References: [Meta Trial Reels announcement](https://about.fb.com/news/2024/12/trial-reels-try-content-non-followers-first-see-what-perfoms-best/) and [Instagram Content Publishing API guide](https://developers.facebook.com/docs/instagram-platform/content-publishing/).



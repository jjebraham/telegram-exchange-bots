# Kiani Instagram Trial Reels

This add-on creates one original Persian text-card Reel each Istanbul day. At 20:30, it ranks the eligible crypto and economy news collected in the preceding 24 hours and selects the highest-scoring distinct story. The existing private Telegram news bot also accepts an administrator-only `/trial <URL>` command.

## Admin use

- Send `/trial https://publisher.example/article` in a private chat with the configured Telegram bot.
- Optional text beside the one link is accepted but ignored by the content renderer; the publisher article is the source of truth.
- A bare URL remains an ordinary Instagram Feed-news request.
- Only the already approved publisher list, a fresh original article passage, a verified Persian translation, and the existing publishing-quota guard qualify. For an explicit admin `/trial` request, useful opinion/analysis from an approved publisher may qualify; ordinary automatic selection remains hard-news-only. Tweets, Reddit posts, and other unreviewed publishers do not qualify.

## Publishing and safeguards

- Automatic selection runs at 20:30 `Europe/Istanbul`; it does not run immediately during installation.
- Automatic and admin requests share a one-Reel-per-Istanbul-calendar-day limit.
- The video is published with `share_to_feed=false` so it stays out of the normal feed while Instagram tests it with non-followers.
- Reels are created with `media_type=REELS` and `trial_params.graduation_strategy=SS_PERFORMANCE`. Instagram, not this publisher, decides whether and when a Trial Reel is shared with followers. Meta does not expose a numeric auto-graduation threshold to this system.
- A rejected/uncertain Meta response never falls back to an ordinary Reel. An uncertain publish is held for review and reserves that day's slot.
- The Reel contains original branded motion cards and the verified Persian title/summary. It does not copy a publisher photo. Full summary text is retained; if it cannot fit the reviewed layout, creation is skipped.
- Soundtracks are selected from two reviewed Wikimedia Commons recordings by Rafael Krux. For each run, the API must return the expected creator, CC BY 4.0 license, identity hash, file type and size; the downloaded audio must match its pinned hash. The Reel caption credits the track, links its source and license, and indicates that it was shortened and faded. Source metadata is stored alongside the private publication record. A failed music check falls back to the existing silent AAC track.
- Trial Reel records live in a separate private database. The normal two-hour/200-view Feed-news deletion worker and delayed-Story worker do not process them. Their article URL and event are added to ordinary news deduplication history.
- Container status is checked by the existing private Telegram worker. Publishing is sent only after Meta reports `FINISHED` and the current quota/Story reservation guard passes.

## Install

Prepare the pinned runtime first and review the extracted revision. Then install with `--install`. Installation reuses the existing Telegram bot token and private admin list; it requests no new credentials and publishes nothing. It requires the existing publisher account, Kiani logo/fonts, Pillow with Arabic shaping support, FFmpeg/ffprobe, the active news quota guard, and the current public HTTPS media directory.

The automatic candidate selector can spend the normal source collection and DeepSeek assessment calls at 20:30. If no eligible current story qualifies, it records a no-candidate result and skips that day. A failed video render or unsupported Trial Reel API response also results in no publication.

## Known platform limitation

`SS_PERFORMANCE` requests Instagram's automatic graduation behavior. It is not a promise of follower distribution or reach. Meta's Trial Reels explanation says Instagram bases its automatic decision on views during the first 72 hours; the account's API access/eligibility is ultimately confirmed only when Meta accepts the first Trial Reel container.

References: [Meta Trial Reels announcement](https://about.fb.com/news/2024/12/trial-reels-try-content-non-followers-first-see-what-perfoms-best/) and [Instagram Content Publishing API guide](https://developers.facebook.com/docs/instagram-platform/content-publishing/).


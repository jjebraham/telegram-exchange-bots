# Local narrated Reels while RunPod is deferred

RunPod rendering and lifecycle controls are deferred. Do not modify the installed
RunPod watchdog or its unresolved lease during this rollout.

The current Reel renderer uses local libx264. Narration stays disabled until
`REEL_ELEVENLABS_ENABLED=true` is explicitly configured. Existing production is
still available at the previously installed revision; staging these files does
not alter its launchers or cron entries.

## Private preparation

1. Stage the exact reviewed revision with `run_trial_reels.py`, without `--install`.
2. Run the offline tests in `voice_review`.
3. Run `reel_voice_tool.py review`. Enter real human scores for pronunciation,
   naturalness, news-presenter tone and 1.5x clarity. Approval is a separate
   explicit decision. Scores below 80, serious pronunciation errors and
   unavailable/unverified voices remain inactive. The four known voice IDs are
   retained. The other nine candidates remain test-only until IDs and samples
   are verified; no IDs or scores are invented.
4. Run `check_local_voice.py`. It reads the existing registry, key presence,
   preview checksums and local usage. It makes no network calls.
5. Existing `configure-secrets` safely stores ElevenLabs and private Telegram
   credentials on Selenium. It does not evaluate shell content or activate any
   feature. Never store these credentials in this repository.

## Settings and activation

`~/.config/kiani-instagram-voice-review/local-render.env` is optional private
KEY=value data. It is read by the staged production Reel entry point, not by
the old installed runtime. Supported keys:

```
REEL_ELEVENLABS_ENABLED=false
ELEVENLABS_MODEL=eleven_v4
REEL_NARRATION_SPEED=1.5
REEL_MUSIC_VOLUME=0.20
REEL_AUDIO_DUCKING_ENABLED=true
```

An optional `REEL_ELEVENLABS_MONTHLY_CHAR_LIMIT` is a positive integer. It limits
newly submitted characters per UTC month, including uncertain calls, in each
cache ledger. It is not a provider credit or currency limit. Comparison-sample
and Reel caches have separate ledgers. Earlier account usage is unknown to the
new ledger. Check the ElevenLabs dashboard for actual balance and charges.
Use private file permissions (0600). RunPod settings are not accepted here.

Before production activation, confirm human scores, cap/budget, current private
preview and active-runtime checks. Use the existing pinned runtime activation
workflow and retain its prior launchers/configuration for rollback. First test
one explicitly requested Instagram canary, then inspect it before enabling
scheduled narration. Do not change the posting schedule as part of this step.
Production activation has not been performed by the preparation commands.

## Reliability and accounting

Random selection is uniform among eligible voices after excluding the last
published and currently reserved voice. Overrides still require approval.
Reservations and confirmed publication history survive restarts. Narrator,
model, speed, renderer, distinct image count, render duration, cache usage and
submitted characters are also stored with each newly narrated Reel.

Narrated production requires two distinct already-verified images before a
voice call. Complete sentence fit is checked before synthesis. The renderer
preserves the existing template and synchronized animation. H.264/AAC format,
1080x1920 frame size and duration are checked before a Meta container request.
Music remains from the licensed pool with topic matching, rotation, caption
credits, a 20% base-volume multiplier and ducking.

A durable reservation precedes a billable narration call. A lost response or
crash leaves a request needing review; the same narration is not automatically
charged again. Successfully received source audio/alignment are retained until
local conversion succeeds, allowing local retries without another API call.
Verified audio is cached by text, voice, model, speed and display-token mapping.
`reel_voice_tool.py usage` reads the character ledger without service calls.

## Performance observations

`reel_voice_performance.py --runtime RUNTIME` produces a local report.
Adding `--collect` explicitly makes bounded GET-only Meta requests using the
existing private analytics transport. It never publishes, deletes or changes
voice probabilities. Run this in the 24–26-hour observation window for each
published narrated Reel; observation scheduling is a later deployment step.
Previously collected observations are reused for the checkpoint.

Reports show views, reach, follows, and engagement as
(likes + comments + saves + shares) / reach when all components are available.
They group broad topic, mode, duration band, four-hour publication window and
weekend status, and compare the same 24–26-hour age window. These are
descriptive groups, not causal rankings. Missing metrics remain null.
Average watch time and completion rate stay unavailable until a verified
account/API source is integrated; average watch time divided by duration must
not be reported as a completion rate. No performance-based probability changes
or automatic narrator activation are made.

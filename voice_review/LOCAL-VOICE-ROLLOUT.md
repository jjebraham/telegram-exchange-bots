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
3. Run `reel_voice_tool.py enroll-evaluation Sahar Aylin Shahram Adrian` to
   apply the user's permission to evaluate the four verified sampled voices on
   Reels. Existing ratings are preserved and marked provisional. Evaluation
   enrollment has no minimum score. New candidates need verified available IDs,
   checked samples and explicit enrollment; unavailable voices stay inactive.
   Run `review` to revise provisional opinions at any time. These opinions do
   not change probabilities or remove an enrolled voice for scoring below 80.
   Serious pronunciation errors disable the voice. Optional `review --final`
   retains the earlier 80-point final-approval workflow. Human ratings and all
   changes remain in a persistent review history.
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

Before production activation, confirm evaluation enrollment, cap/budget, current private
preview and active-runtime checks. Use the existing pinned runtime activation
workflow and retain its prior launchers/configuration for rollback. First test
one explicitly requested Instagram canary, then inspect it before enabling
scheduled narration. Do not change the posting schedule as part of this step.
Production activation has not been performed by the preparation commands.

After enrollment, `reel_voice_tool.py configure-local --enable` sets the
persistent narration flag. Install the staged runtime with the existing pinned
`run_trial_reels.py --install` workflow. This uses local rendering and keeps the
same scheduled slots. For immediate narration rollback, run
`reel_voice_tool.py configure-local --disable` using this pinned runtime.
The activation backup also retains prior launchers, crontab and private admin
configuration for a complete runtime rollback. No RunPod configuration is touched.

## Reliability and accounting

Random selection is uniform among eligible final-approved or explicitly
evaluation-enrolled voices after excluding the last
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
published narrated Reel. Narrated-runtime activation installs a GET-only
observation job every 30 minutes within the existing managed cron block.
Posting slots are unchanged. A process lock and saved checkpoints prevent
overlapping or duplicate observations.
Previously collected observations are reused for the checkpoint.

Reports show provisional human opinions separately from views, reach, follows, and engagement as
(likes + comments + saves + shares) / reach when all components are available.
They group broad topic, mode, duration band, four-hour publication window and
weekend status, and compare the same 24–26-hour age window. These are
descriptive groups, not causal rankings. Missing metrics remain null.
Average watch time and completion rate stay unavailable until a verified
account/API source is integrated; average watch time divided by duration must
not be reported as a completion rate. No performance-based probability changes
or automatic narrator activation are made.

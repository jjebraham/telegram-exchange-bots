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

### Speech-only Persian pronunciation marks

The active staged protocol now requests sparse annotations of words identified
by section and word indices. Whole-sentence rewriting is not used. Each proposed
word must preserve every original character and only insert valid marks; bad,
out-of-range or duplicate edits are ignored independently. The application
rebuilds speech from the original words and whitespace, then validates the full
result. A changed model proposal can no longer discard all other valid words.

For migration, a saved rejected sentence response may supply marks only for
unchanged words at stable positions, with unchanged immediate neighbors.
Sections with a changed word count are skipped. Altered words and their
neighbors keep their original pronunciation. The recovered result is fully
validated and cached under the word-annotation protocol without a new model
request. Old cache entries and attempt counts are retained. This preserves
literal news content; it does not prove that every accepted vowel is correct.

`check_pronunciation.py --runtime RUNTIME --cached-only --reel-id SAVED_ID`
attempts this recovery without DeepSeek. The live checker also prefers recovery
before making one new word-annotation request. It displays the number of added
marks. Private previews can target that exact saved Reel with `--reel-id` and
use `--cached-pronunciation-only` to prohibit DeepSeek and stop before audio
when no checked pronunciation is cached. New audio still uses ElevenLabs
credits. This provides a private audio check before production activation.

Narrated Reels make one bounded DeepSeek request for all expanded speech
sections together, using the title and surrounding sentences for context.
Only additive short-vowel/ezafe marks, shadda, sukun and supported tanwin are
accepted. Every existing letter, digit, space, zero-width joiner and punctuation
mark must remain exact. The displayed story is unchanged. Existing number,
date and currency expansion happens before the pronunciation pass.

The result is cached independently of voice so it can be reused across
narrators. Cache hits are validated again. Lost, malformed or text-changing
results fall back to the original speech script without an automatic second
DeepSeek request. A missing key also uses the original script. The existing
production DeepSeek transport accounts for the call within a tracked Reel run.
This is an extra model request on a new pronunciation-cache miss; it can incur
DeepSeek charges. Cache reservations avoid repeated charges after a lost
response, but they cannot establish the provider's final bill.

Word offsets are remapped to the marked speech while preserving visible
tokens. Alignment may include or omit combining marks, but its base characters
must still match. ElevenLabs caching includes the exact speech script, so old
unmarked audio cannot be mistaken for corrected audio. Model-generated marks
can still be linguistically wrong; review a real private audio preview.

`REEL_PRONUNCIATION_ENABLED=false` in the private local-render settings opts
out of the pronunciation pass while retaining narration. It defaults on in
this staged update. `check_pronunciation.py --runtime RUNTIME --live` inspects
one cached DeepSeek result for the latest saved published Reel, without an
ElevenLabs or Instagram call. `preview_voice_reel.py --runtime RUNTIME
--latest --voice Sahar --send` renders and sends a private preview through the
existing verified test channel. New audio uses ElevenLabs credits. Test this
update privately before switching the active production runtime.

Pronunciation failure diagnostics record fixed categories, an optional HTTP
code/finish reason, affected section number, and text-length/change flags.
They do not print keys, raw provider errors or rejected text. Parsed rejected
candidates are retained in the owner-only cache for offline investigation.
`check_pronunciation.py --runtime RUNTIME --audit` only reads these diagnostics.
Older generic failures have no recoverable reason. An explicit
`--live --retry-one --reel-id SAVED_ID` can make one additional request for a
failed entry, limited to two attempts total; ordinary narration never retries
it automatically. Use the saved Reel ID to avoid testing a different latest
article. This diagnostic does not request ElevenLabs or publish anything.

DeepSeek credentials are loaded by explicit live entry points, not by the
testable narration-preparation function. Integration tests isolate state in a
temporary directory and verify that preparation cannot read a production key
from the home directory or make an unintended DeepSeek request. An earlier
version could load the real key in Linux tests; historical billing cannot be
established from that version's generic fallback output.

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

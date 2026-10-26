# AlanChande image reports: review, deployment and rollback

All five templates render validated publisher output offline with Python,
Playwright and Chromium. The four additional layouts are implemented in
`market_report_templates.py`. USDT and Iranian FX use the requested mobile
layouts with larger main rates and historical details in accompanying text.

## Layouts and assets

| Kind | Logical artboard | Main composition | Sample PNG |
|---|---|---|---|
| usdt | 1200 × 1500 at seven exchanges | Three-column mobile rate table and four summary cards | 2400 × 3080 |
| iran-fx | 1200 × 1500 | Right 13 / left 12 currency rows, rates only | 2400 × 3080 |
| iran-gold | 1200 × 1200 at seven instruments | Five coin rows and two gold rows | 2400 × 2480 |
| turkey-gold | 1200 × 1200 | Four sell/buy rows with Persian/Turkish names | 2400 × 2480 |
| fx-pulse | 1200 × 1200 | Two stacked USD/TL and EUR/TL feature cards | 2400 × 2480 |

Samples add a separate 40 CSS-pixel label row. The new four reports use a
compact amber warning; no data or footer is covered. Production images have no
sample label. USDT adjusts for five through eight validated exchange rows;
Iranian gold adjusts when optional gold instruments are absent. Production
images are never silently stretched or cropped to fit Telegram.

The 25 locally bundled MIT-licensed SVG flags are selected by currency code,
independently of incoming emoji. Fixture flags are also corrected. Detailed
provenance, upstream URLs, hashes and the license are in
`market_image_assets/flags/`. Vazirmatn and its SIL OFL license remain bundled.
Gold illustrations and the faint circular A watermark are original inline
SVGs. No external fonts, emoji rendering, asset downloads or image-generation
service is required during publication.

## Iranian FX on phones

The Iranian FX image shows only currency names, canonical flags/codes and toman
rates, without column headings, matching the revised 4:5 reference. Larger flags,
rounded boards, a unit pill and left-aligned prices keep the visual hierarchy
clear. The 25 currencies keep the same right-13 / left-12 order. Price text is
62 logical pixels (about 20 pixels at a 390-pixel phone width), up from 35;
exceptionally long values still fit safely. Daily/monthly percentage columns
are deliberately omitted from this image.

The complete, unchanged verified publisher bulletin follows the photo as a
linked HTML text message. It includes all 25 rates, Δ24H, Δ1M, source time,
unit, availability notes and disclaimer. Both outputs use one fetched snapshot.
The complete table exceeds Telegram's 1024-character photo-caption limit, so
it uses `sendMessage` (4096 characters) with a reply to the photo. Length is
checked before sending; details are never truncated. Gold remains one photo;
Turkey FX pulse includes its full caption as described below. Sample mode
labels both the image and the full text.

Success requires Telegram receipts for both messages. A partial delivery
reports the already-sent photo ID and does not automatically retry the photo.
The manual helper saves `.details.html` and `.receipt.json` beside the PNG;
inspect the channel before retrying an ambiguous delivery. The rate/history
calculations and market-safety requirements remain unchanged.

The guarded installer recognizes the exact earlier photo-only integration,
but requires `--upgrade-integration` to migrate it. `--upgrade-renderer` alone
cannot change that publisher integration. The reviewed SSH deployment helper
passes both flags; do not run it against production before visual approval.

## USDT on phones, with full text beneath the photo

The USDT image has three columns: exchange, **your purchase**, and **your sale**.
It retains the exchange logos and all four summary cards, with 70-pixel table
rates (about 23 pixels at a 390-pixel phone width). Percentage columns are
omitted from the image. The full daily/monthly table remains in the text,
with dashes where actual historical values are unavailable. The artboard
adjusts by 104 logical pixels for each exchange above/below seven.

The first publisher value is `buy_toman`, what the customer pays to buy USDT;
the second is `sell_toman`, what the customer receives when selling it. Values
and summaries are never swapped or recalculated. The source text's SELL/BUY
header uses the exchange's perspective; `image_post_details` changes only that
display header to customer BUY/SELL and adds a short Persian explanation.
Every source row, percentage, source clock and summary value is preserved.

USDT's complete text normally fits directly in the photo's HTML caption, so
one Telegram post contains both image and text. If it exceeds the 1024-character
caption limit, it falls back to linked full text; nothing is cut. Source checks
are enforced before either output is sent. The manual preview command remains
`--kind usdt --send-test` and always targets TEST.

The previous USDT golden HTML digest is superseded by this explicit redesign.
Tests verify three-column prices, buy/sell mapping, summaries, readable type,
missing history, five/eight-row bounds, one-fetch text consistency, complete
HTML caption delivery and long-text fallback.

## Turkey FX pulse

The two main USD/TL and EUR/TL rates use black 88-pixel type, reduced from 116.
The layout, flags, units, original four-decimal midpoints and daily/monthly
panels remain. The complete original verified bulletin is included as the
photo's HTML caption; oversized future text uses the existing linked fallback.
No source rate, midpoint calculation, percentage, source time or safety rule
is changed. `--kind fx-pulse --send-test` fetches one enforced snapshot for
both image and text and always targets TEST.

## Verified data contracts

| Report | Producer fields preserved | Historical periods |
|---|---|---|
| USDT | `buy_toman` is the first numeric value (customer purchase); `sell_toman` second | Existing daily/monthly publisher fields |
| Iranian FX | Toman value for each canonical currency, including unavailable slots | Explicit Δ24H and Δ1M from `build_iran_fx_post` |
| Iranian gold | Publisher's toman price per exact instrument name | Producer's explicit Δ24H / Δ1M pair; legacy daily-only text leaves monthly `—` |
| Turkish gold | Producer SELL first, BUY second; red sell, green buy | Explicit Δ24H and optional declared Δ1M columns; legacy monthly is `—` |
| Turkey FX pulse | Producer's already-calculated Kapalıçarşı midpoint, exactly four decimals | Explicit Δ24H and optional declared Δ1M columns; legacy monthly is `—` |

The original gold/pulse mockups do **not** define data semantics. Values are not
moved between periods to match those pixels. The live server's newer producers
already supply monthly fields; the renderer accepts both those explicitly
declared daily/monthly schemas and the repository's legacy daily-only text.
Monthly fields are passed through unchanged when supplied, with a dash only
when unavailable. Mismatched headers/field counts fail closed. Typed immutable
payloads parse these contracts; no rate conversion, rounding, midpoint,
history, freshness or quorum calculation is duplicated in the renderer.

Unknown, duplicate, malformed or incomplete required rows fail closed. Missing
values stay as dashes. All 25 FX slots are present, ordered canonically with USD
through AZN on the right and DKK through QAR on the left. Unavailable FX values
retain their slots and an explanatory note.

Live header time comes from the publisher's clock for the correct city, or a
dash if missing. The Jalali date is the local rendering date. Explicit
timezone-aware test timestamps reproduce the supplied references. Teheran and
Istanbul midnight boundaries are tested separately.

Browser checks wait for fonts and images, fit unusually long approved strings
inside their slots, then reject clipped fields or missing artwork before
`sendPhoto`. The isolated worker receives UTF-8 explicitly on every platform.

## Local validation and visual comparisons

```sh
python -m pip install 'playwright==1.57.0' Pillow
python -m playwright install chromium
RENDER_PNG_TESTS=1 python channel_split/test_market_images.py -v
RENDER_PNG_TESTS=1 python channel_split/test_market_report_templates.py -v
python channel_split/test_market_image_deploy.py -v
python channel_split/test_market_image_delivery.py -v
python -m unittest discover -s tests -p test_channel_split_market_safety.py -v
python -m unittest discover -s tests -p test_channel_split_hybrid_usdt.py -v
python -m unittest discover -s tests -p test_channel_split_market_pulse.py -v
python -m unittest discover -s tests -p 'test_channel_split_*history.py' -v
bash -n channel_split/deploy_images_via_ssh.sh

# Five visibly illustrative PNGs, never sent:
python channel_split/visual_market_images.py --kind all --output-dir image-previews

# Four reference comparisons, with input directories named by template kind:
python channel_split/visual_market_images.py --kind all \
  --reference-dir /path/to/references --output-dir /path/to/review
```

The comparison input convention is `<kind>/approved-reference.png` and an
optional `<kind>/before.png`. Each report gets its own aspect ratio, normalized
reference overlay, difference image, before/after sheet and diagnostic JSON.
Only the dedicated test-label row is excluded. No dynamic field is masked.
Pixel errors cannot establish visual acceptance; inspect the actual images.

## GitHub Actions

`.github/workflows/alanchande-image-previews.yml` runs validation on feature
branch pushes and pull requests, and supports manual runs. It uploads all five
watermarked PNGs as the `alanchande-five-template-previews` artifact for 14 days.
It has read-only repository permissions, no deployment step, and no bot/SSH
secrets. This provides a review artifact without posting or activating anything.

The existing default-branch `.github/workflows/alanchande-image-posts.yml`
remains the production deployment entry point. Its helper now transfers the
new report module and complete artwork folder. Its original preview mode sends
five photos and installs into the live publisher checkout; do not use it for a
four-photo isolated review. Do not select `activate` without explicit approval.

## Isolated four-photo review

Stage the current source files and complete artwork folder together, outside
the production checkout. Keep all credentials on the server in their existing
protected environment. Do not copy `.env`, private keys or production databases
into a package, repository or workflow artifact.

These existing commands remain supported from a correctly staged directory:

```sh
/usr/bin/python3 manual_image_preview.py --kind iran-fx --sample --send-test
/usr/bin/python3 manual_image_preview.py --kind iran-gold --sample --send-test
/usr/bin/python3 manual_image_preview.py --kind turkey-gold --sample --send-test
/usr/bin/python3 manual_image_preview.py --kind fx-pulse --sample --send-test
```

`--output /path/to/proof.png` optionally selects the review PNG path. The
destination remains hardcoded to `@alanchandetest`. Each invocation sends one
photo. Maintain a per-template receipt/intent record to avoid duplicates if an
upload result is uncertain; inspect the channel before retrying. The four-photo
review must not invoke the five-photo production deployment helper.

## Production readiness and guarded installation

**Do not install or activate production image publishing until the final five
appearances have explicit user approval.** The review does not modify live
source, credentials, schedules, market histories, channel settings, or services.

Before any production installation, inspect its dirty checkout and preserve
unrelated work:

```sh
git -C /home/kianirad2020/telegram_bot_repo status --short
```

The renderer package must contain `market_images.py`,
`market_report_templates.py`, `deploy_market_images.py`, and the full
`market_image_assets/` folder. Run the guarded installer dry run first:

```sh
python deploy_market_images.py --repo /home/kianirad2020/telegram_bot_repo --upgrade-renderer
# Only after approval, inspection and successful dry run:
python deploy_market_images.py --repo /home/kianirad2020/telegram_bot_repo --upgrade-renderer --apply
```

Existing publisher integration must match its exact known anchors. A mismatch
must be reviewed; do not force it, reset the checkout, or overwrite local edits.
An upgrade leaves the publisher bytes intact and backs up the renderer,
additional module and every required asset. It does not activate image mode,
restart a service, send a photo, or touch a history database.

Live validation must still pass before image mode can be activated. If USDT
reports `SAFETY usdt: BLOCKED`, keep it blocked; do not substitute fixtures or
relax freshness, trading-state, source independence or quorum rules.

TGJU can return a cached HTTP 200 response with an empty body. The Iranian FX
fetcher retries that same source/path once with a fresh cache key; a second
empty response raises an explicit source error. Nonempty incomplete/challenge
pages still fail immediately, and independent market verification remains
required. This transport recovery never substitutes rates from the mockups.

## Safe rollback

No production rollback is needed for an isolated review. For an installed image
publisher, return the next scheduled reports to text by changing only the
`ALANCHANDE_POST_FORMAT` setting in the protected environment. This explicit
manual rollback snippet preserves other entries, saves a mode-0600 backup, and
atomically replaces the file without printing credentials:

```python
from pathlib import Path
from datetime import datetime
import os
import re
import tempfile

path = Path('/home/kianirad2020/telegram_bot_repo/channel_split/.env')
original = path.read_text(encoding='utf-8')
backup = path.with_name('.env.before-text-rollback-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
with backup.open('x', encoding='utf-8') as output:
    output.write(original)
backup.chmod(0o600)
lines = [line for line in original.splitlines()
         if not re.match(r'^\s*(?:export\s+)?ALANCHANDE_POST_FORMAT\s*=', line)]
lines.append('ALANCHANDE_POST_FORMAT=text')
with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False, encoding='utf-8') as output:
    output.write('\n'.join(lines) + '\n')
    temporary = Path(output.name)
temporary.chmod(0o600)
os.replace(temporary, path)
print('Text publishing selected; other settings preserved')
```

For a template-code rollback, use the **specific backup directory printed by
the installer**, after selecting text mode. Restore `market_images.py`,
`market_report_templates.py` if that backup includes it, and the matching
`market_image_assets/` contents together. Do not restore a publisher backup over
later unrelated changes. Do not remove market databases, reset Git, alter the
other bots, or change credentials/channel permissions.

## Visual limitations

The supplied AI-generated references have no exact typeface or layered/vector
source. The licensed font, reconstructed skyline/coins/bars/watermark and SVG
flags have small shape/spacing differences. Some historical mockup percentages
must differ because their apparent period is not supported by the producer.
Zero and missing movements remain semantically neutral. Sample values and
timestamps are illustrative. Telegram can resize/recompress photos; acceptance
must include the actual test-channel images, not just the original PNGs.

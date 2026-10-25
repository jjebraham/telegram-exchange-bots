# USDT reference implementation and visual acceptance

This change rebuilds only the USDT infographic. The remaining four templates
retain their existing layouts until the USDT appearance is approved and their
own original references are supplied.

## Reference assessment and implementation choice

The supplied current output had an oversized title-to-table rule, flat Tether
symbol, letter badges, simplified skyline, small/light numbers, summary labels
and values shifted toward the right, generic character icons, and a floating
test watermark that obscured the bottom summary values. The footer used a
yellow handle and a generic arrow rather than the reference's white handle and
Telegram symbol. Percent signs and negative signs relied on mixed RTL shaping.

The approved reference is 1122 × 1402. Its proportions normalize closely to a
1200 × 1500 design: header 132 px, title 186 px, table beginning at 318 px,
72 px table header, about 90 px per row, two 165 px summary rows, and an 84 px
footer. The original illustration has slightly irregular row geometry; the
implementation deliberately uses uniform rows for repeatable dynamic data.

Two approaches were evaluated. Pure SVG/HTML would keep everything scalable
but approximate the dimensional coin and distinctive exchange artwork. A full
flattened background would preserve sample numbers and prevent safe variable
row counts. The selected hybrid uses **only isolated decorative crops** from
the supplied reference, original SVG icons/skyline, and HTML/CSS for every
changing field. No sample value or date is embedded in any artwork.

## Behavior and safeguards

- Embedded OFL-licensed Vazirmatn makes Persian typography independent of
  server-installed fonts. All assets are embedded in the HTML and network
  requests are blocked in the screenshot browser.
- Five RTL columns preserve the publisher's customer-facing convention:
  first numeric column = customer purchase (`buy_toman`, red); second =
  customer sale (`sell_toman`, navy), despite the legacy preformatted header's
  SELL/BUY wording. Prices and summary values are never recalculated here.
- Percent signs, sign, magnitude, decimal mark and Persian digits are displayed
  consistently in isolated LTR runs. Missing values remain `—`.
- Real publisher summaries use Persian exchange names; table rows use Latin
  identifiers. Both refer to the same validated exchange, with space/ZWNJ
  normalization for Bitpin. Unknown/duplicate exchanges and malformed values
  fail closed.
- A five-to-eight-row report adjusts its canvas by 90 CSS px for each row.
  Long approved values shrink within their own slots without being rounded or
  truncated. A browser geometry check rejects overflow before `sendPhoto`.
- Four colored cards reserve separate positions for label, value, unit, icon
  and exchange name. A missing sell summary displays a dash.
- The watermark occupies its own 40 px row above the artwork. It cannot cover
  the table or cards. USDT proof PNGs are rendered at 2× resolution.
- Production time comes from the validated publisher's own Tehran clock.
  If absent it displays a dash. Explicit test timestamps require a timezone.
  The Jalali date is the local rendering date, as in the existing architecture.
- Authentication, schedules, source validation, history calculations, safety
  quorum, publication recording, and text fallback remain in the publisher.
  No market data is fetched by the renderer.

## Repeatable visual comparison

From the repository root, with Playwright/Chromium installed:

```sh
python -m pip install 'playwright==1.57.0' Pillow
python -m playwright install chromium
python channel_split/visual_market_images.py \
  --reference /path/to/approved-usdt-reference.png \
  --before /path/to/previous-preview.png \
  --output-dir /path/to/review
```

The fixed, clearly labeled sample uses the reference's original fixture figures
and 2026-10-25 21:30 Asia/Tehran. It never sends Telegram messages. Outputs are:
`usdt-after.png`, `reference-before-after.png`, `reference-overlay.png`,
`reference-difference.png` and `visual-metrics.json`. The comparison removes
only the separate test-label row and normalizes both images to 1200 × 1500.
It masks no market text, cards, or geometric mismatches. Pixel scores are
diagnostic; inspect typography, spacing, and the actual Telegram photo too.

## Tests

```sh
RENDER_PNG_TESTS=1 python channel_split/test_market_images.py -v
python channel_split/test_market_image_deploy.py -v
python -m unittest discover -s tests -p test_channel_split_market_safety.py -v
python -m unittest discover -s tests -p test_channel_split_hybrid_usdt.py -v
bash -n channel_split/deploy_images_via_ssh.sh
```

The browser suite covers all five existing templates, the isolated Python
worker, the USDT five/eight-row bounds and intermediate counts, long values,
RTL formatting, actual publisher output, missing sell values and time, and the
2400 × 3080 watermarked sample. The deployment test uses disposable copies.

## Preview and deployment

The requested review happens in an isolated staging directory, not the live
publisher checkout. Copy `market_images.py`, `test_market_images.py`,
`manual_image_preview.py`, and the entire `market_image_assets/` directory
together. After inspecting the PNG and passing tests, send exactly one sample:

```sh
python manual_image_preview.py --kind usdt --sample --send-test \
  --output /path/to/review/usdt-review.png
```

The destination is hardcoded to `@alanchandetest`. The existing protected
production environment provides authentication; no token is copied into the
review package, printed, or committed.

**Visual approval is required before production installation/activation.**
After approval, the existing default-branch workflow remains the deployment
entry point. Its helper now transfers the bundled assets. Its original preview
stage still publishes five test images; it should not be invoked when only one
USDT review is intended.

For a reviewed manual upgrade, first run the guarded installer without
`--apply`; use `--upgrade-renderer` for an existing integration. The installer
requires the complete exact publisher integration before updating a renderer,
backs up renderer/artwork, and leaves the publisher bytes unchanged during an
upgrade. A mismatch must be reviewed manually. The installer does not activate
image mode or restart anything.

```sh
python deploy_market_images.py --repo /home/kianirad2020/telegram_bot_repo --upgrade-renderer
# Only after approval and successful dry run:
python deploy_market_images.py --repo /home/kianirad2020/telegram_bot_repo --upgrade-renderer --apply
```

## Rollback

Set `ALANCHANDE_POST_FORMAT=text` in the protected production
`channel_split/.env` to return the next scheduled publications to text. Preserve
all other environment entries and do not print bot tokens. The installer backup
location is printed on successful installation. Restore `market_images.py` and
its corresponding `market_image_assets/` from that same backup if the artwork
itself must be reverted. Restore a publisher backup only when a new integration
was installed and no later unrelated edits would be lost. Do not use a checkout
reset or change the other bots.

## Remaining differences

The reference's exact typeface and original vector/3D source files were not
supplied. Vazirmatn is licensed and close, but its letterforms and text metrics
differ. The skyline, clock/calendar, summary icons and Telegram symbol are
vector reconstructions. Tiny shadows, texture and gradients differ. Exchange
marks and the coin come from approved raster artwork and cannot gain real
detail from the 2× output. Their provenance and name-only fallback are in
`market_image_assets/SOURCES.md`; they are not claimed to be a newly licensed
official vector brand kit. Telegram also resizes/compresses photos. Human
approval, rather than a pixel score, determines visual acceptance.

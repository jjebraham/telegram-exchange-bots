# Reviewed selector dependencies and readable-carousel renderer

## Option B template update

Only `instagram_news_renderer.py` is intentionally updated from the original
helper listed below. It now renders a photo/headline cover and full, 64px
summary pages for one story per carousel. Parsing, translation, source selection
and the existing carousel publication helper remain byte-identical. The runtime
fingerprint and manifests identify the new layout. Original source dates,
caption attribution and all summary text are preserved. This does not change
hourly slots, daily limits, eligibility, Story timing or news retention.

The table below records the original provenance, not the new renderer's hash.

The original helpers were copied byte-for-byte (UTF-8/LF) from:
`ed50327ee0bd0082be479606f26648a46e35c636` in
`jjebraham/telegram-exchange-bots`.

| File | Git blob SHA |
|---|---|
| economy_news_picker.py | 37db43f63b908f4d82d473d0253462db94a857df |
| economy_news_translation.py | a1b0678a9683f2c48d066efb152f9531c4491524 |
| instagram_crypto_news.py | d6e574d251ee66ba24d1bc58e30f5c4c6db5b900 |
| instagram_news_renderer.py | 8f65b9f2cb328cb94581093fb1eb0ff8af68d4e0 |

The trial imports only their parsing, import, translation and rendering helpers.
Their publisher entry points are not executed. No helper is installed over an
active publisher. The existing news importance function supplies the comparison
score; the new event assessment is in `crypto_news_trial.py`.

Retain this directory with the trial checkout. Independently deployed rates,
news, economy and history branches do not necessarily contain every helper at
their repository root.

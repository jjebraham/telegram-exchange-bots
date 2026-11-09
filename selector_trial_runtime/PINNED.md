# Reviewed selector dependencies and readable-carousel renderer

## Option B template update

`instagram_news_renderer.py` and `economy_news_translation.py` are intentionally
updated from the original helpers listed below. The renderer makes a photo/headline
cover and full, 64px summary pages for one story per carousel. Source selection
and the existing carousel publication helper retain their
reviewed behavior. The translation helper now requests natural, complete Iranian
Persian news sentences, preserves financial meaning and uncertainty, and keeps
pronunciation marks out of display text. New prompt-version cache keys avoid
reusing older compressed wording; prior cache rows remain intact. Source-number,
length, Persian-text and link checks are retained. Equivalent decimal/digit
formats now compare exactly without rounding or rescaling. Unsupported numbers
receive one targeted correction attempt, with rejected parsed news fields retained
privately and never cached as a successful translation. The runtime
fingerprint and manifests identify the new layout. Original source dates,
caption attribution and complete rendered summary text are preserved. This does not change
hourly slots, daily limits, eligibility, Story timing or news retention.

The table below records the original provenance, not the hashes of the updated renderer or translation helper.

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

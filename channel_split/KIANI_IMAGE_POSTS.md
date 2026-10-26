# Kiani customer image posts

Four existing customer posts use the requested Kiani green-and-white style:

| Post key | Image |
|---|---|
| `kiani-rates` | Daily TRY/USDT customer buy/sell board and both cross rates |
| `kiani-try` | Large green customer purchase rate, blue customer sale rate and contact details |
| `kiani-examples` | Toman deposited in Iran to receive fixed TRY amounts in Turkey |
| `kiani-examples-reverse` | TRY deposited in Turkey to receive fixed toman amounts in Iran |

The renderer parses the existing formatter output. It does not fetch rates,
choose pricing sources or recompute conversions. The live customer-rate source,
canonical TRY source, customer buy/sell conventions, calculator rounding and
schedules remain in the existing publisher. Source-function ASTs were compared
before deployment. Missing, repeated, malformed or mismatched-direction fields
stop rendering before a photo is sent.

Main prices are large enough for a phone screen. The daily board uses Persian
digits and a compact portrait; the focused TRY card retains large Latin prices
as in the reference. Both calculator cards label what the customer deposits and
receives. Contact URLs and order handles come from the original post text.
The official Kiani logo is bundled, along with its public source and checksum.
Fonts, flags and illustrations render offline. No screenshot navigation controls
or sample values appear in live images.

## Presentation and rollback

`KIANI_POST_FORMAT=image` selects one image with the three channel-link caption
lines already used for market images. It sends no duplicate full text.
`KIANI_POST_FORMAT=text` restores the original text formatter output. The default
is text, and installation alone does not change this setting.

The guarded installer recognizes the four existing producer calls, assigns their
post keys and adds the Kiani send branch. It preserves an existing AlanChande
image branch. Unexpected anchors or keys stop the patch; source and pricing
functions are not replaced. Application backs up the exact prior files. Protected
configuration backups and live rollout receipts are retained privately.

## Review and validation

```sh
python channel_split/test_kiani_images.py -v
python -m unittest discover -s tests -p test_channel_split_kiani_posts.py
python channel_split/visual_kiani_images.py --output-dir kiani-previews
python channel_split/deploy_kiani_images.py --repo REVIEW_CHECKOUT
```

The preview command uses visibly labelled fixture data. Use `--skip-sheet` when
the runtime has Playwright but not the optional Pillow contact-sheet dependency.
Seven new tests check direction/value preservation, malformed input, offline
artwork, an unchanged pricing function, migration, backup and idempotency. The
nine original formatter tests pass. Browser checks reject clipped prices,
missing assets and content outside the artboard before posting. Real-rate
previews were generated from read-only exports of the live customer publisher.

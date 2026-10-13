# Fresh Hawala section in the daily rates carousel

The Telegram Hawala bot writes its successful-delivery snapshot only after a
scheduled Telegram message. The Instagram carousel checks that snapshot before
and after collecting the other sources. Production logs showed `expired while
collecting`: the snapshot passed the first check, then exceeded the 15-minute
limit while the other sections were collected.

The new `calculator` source asks the existing Hawala pipeline for a fresh
calculation. It runs a separate process with the running producer's interpreter
and private environment, imports its guarded modules, applies
`hawala_runtime.install_dynamic_pricing`, and calls only
`calculate_hawala_rates`. It keeps the producer's Nobitex/Wallex anchor,
Kraken/Gate equivalent, CurrencyAPI crosses, live admin adjustments, rounding,
and canonical TRY endpoint. No pricing formula or adjustment is duplicated.

The FX cache starts empty, so an old cache from the long-lived Telegram bot
cannot be relabeled as a fresh calculation. The bridge requires all seven
positive integer Toman quotes: USD, EUR, GBP, CAD, AUD, SEK and TRY. Collection
and pre-publication freshness checks retain the 15-minute limit. If a required
source or the canonical TRY endpoint fails, Hawala is omitted with a safe log
message; historical rates are never substituted.

The calculator never starts the Telegram scheduler or calls its send, slot
tracking or snapshot export functions. Telegram API requests are blocked inside
the isolated child, and private source output and exceptions are suppressed.
Neither private environment values nor the producer's source files are saved
to the repository. The running Hawala bot and its successful-delivery snapshot
are not changed.

## Activation

Run `activate_hawala_source.py` from an exact reviewed revision with `--repo`
and `--revision`. The installer expects the reviewed USDT comparison fix to
already be installed. It performs one fresh calculation through the carousel
parser before replacing either module or changing configuration. It acquires
the existing Feed publication lock, backs up the two files and private
environment, installs only the carousel module and source bridge, and sets:

```
INSTAGRAM_HAWALA_SOURCE=calculator
INSTAGRAM_HAWALA_RUNTIME_ROOT=/path/to/existing/kiani-hawala-bot
```

The installed rates launcher and crontab are checked for unexpected changes.
The daily rates Feed remains at 11:30 Istanbul, with one delayed first-slide
Story preview 30 minutes after the actual Feed publication. Activation does
not publish an Instagram or Telegram message. `--check-live` repeats the
read-only calculation through the installed parser when needed.

The legacy `snapshot` source remains available for existing configurations.
Successful live source verification confirms an eligible Hawala section; the
next successful Feed manifest and saved publication state establish whether it
was published. The carousel contains seven slides when USDT, FX and Hawala
are all eligible.

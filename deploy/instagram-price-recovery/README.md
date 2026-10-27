# Customer rates and Iran gold recovery

This repair addresses the observed 27 October failures while retaining source
verification, the approved layouts and the original first daily slots.

## Customer rates

The scheduled run could not parse the customer lira quote; a later owner probe
returned six ordinary numeric values. The original failing API payload was not
captured, so its exact value/type is unknown. The repair handles temporary
unavailability without assuming that malformed or alternate prices are valid.
Explicit null values now receive the existing bounded GET
retry policy. Malformed, non-positive, non-finite, incomplete or crossed quotes
still fail. Customer prices are never calculated from another feed or recalled
from a previous post.

The required customer board is checked before optional sections are collected,
then fetched again immediately before rendering. Both customer slides use that
same final response. Optional USDT/FX/Hawala sections keep their existing rules.
The source preflight reports which optional sections currently qualify.

The original 11:30 Istanbul / 12:00 Tehran start remains. Two additional attempts
start five and ten minutes later. Success uses the existing daily duplicate
guard. A durable receipt is committed before the final Meta publication request;
an uncertain request stops subsequent attempts for reconciliation. A confirmed
response can restore a missing Feed state without posting again. This guard is
initialized only by the customer-rates main program, so importing its unchanged
Graph helper API from the other publishers does not enroll those publishers.

## Iran gold

The morning audit had two overlapping two-source groups for 18K gold. The repair
does not choose the closest pair, prefer a publisher to break a tie, increase a
price tolerance, or turn stale data into a current price.

TGJU now uses the existing restricted Akamai `tgju_current` selector already
verified on Selenium. It reuses the existing feed-only identity and exact host
pin, disables forwarding/configuration, and introduces no administrator command,
new credential or arbitrary URL proxy. One bounded request supplies all seven
native records instead of seven failing profile requests from Google Cloud.

Each TGJU record retains its original rial price, daily range, Gregorian `ts`
and matching Persian/English clock. The owner-provided native timestamps confirm
the Tehran clock convention used here; relay receipt time is never used as
quote time. Native date-only or old individual quotes remain excluded, even if
other records in the same response are fresh. Receipt/cache evidence and exact
native-to-normalized conversion are checked again before publishing.

The existing unique consensus algorithm is unchanged: at least two eligible
publishers per instrument, 0.5% for gold/mesghal and 1% for coins, with Servix
supplementary, current Tehran-day and <=30-minute original clocks, conservative
bounds, coherent denominations/fineness and the original move guard. A genuine
remaining tie still skips the entire Iran board. No guarantee of daily delivery
is made when verified data is unavailable.

Gold starts at 10:00 Tehran, with new attempts at 10:05 and 10:10. The existing
final 10:00–10:15 publication window, daily success/uncertain guards, two-slide
design and optional verified global-metals slide remain. A successful Feed still
gets one delayed Story after 30 minutes.

## Installation and evidence

`run_recovery.py` extracts 23 pinned source/assets files without a repository
checkout, package installation or service restart. Its default is source checks
and a fresh gold layout preview, with no Meta contact. `--target rates` or
`--target gold` isolates a component; the default `both` reports each separately.

`--activate` first repeats the checks for each component. It verifies the exact
owner-confirmed customer-rate source/layout hashes and installed PR74 gold
revision, active UTC cron, original launcher and pinned gold contents. Gold
activation requires a new exact-runtime/assets preview and a new successful
collection in which TGJU corroborates gold18 or mesghal.

Affected publisher locks, immutable gold releases, private backups, concurrent
edit checks and conditional rollback protect activation. The only scheduled
changes are the two bounded retry minutes on each existing daily job. The rates
launcher, private environment/key, source producers, quote adjustments, layouts,
publication/history databases, Story configuration, news policy and all other
jobs are preserved. Each target activates independently, so a blocked gold check
cannot be reported as a successful gold upgrade or silently prevent a valid
customer-rates repair from being reported separately.

Installation never publishes or deletes an Instagram post, starts a catch-up,
or calls an existing test runner. Server source/preview/activation output is
required before deployment or successful scheduled delivery can be claimed.

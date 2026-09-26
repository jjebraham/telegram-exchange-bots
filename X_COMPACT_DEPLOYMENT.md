# Compact Kiani X deployment

Prepared against channel-split commit `2758cbc`. This update has not been
installed on the Selenium server or GitHub's default branch. No posts were sent.

## Scope

Four existing GitHub Actions rate slots remain at 09:12, 12:07, 15:12, 18:12
Istanbul time. All are link-free, including legacy callers requesting links.
The hourly 08:37–22:37 movement checks retain their 0.5% threshold and existing
baseline behavior. Alerts also carry `حواله روی خط واتسپ`.

Eleven new server timers add one daily X version of every other active Telegram
type: banks 09:25, USDT exchanges 10:25, Turkey gold 11:25, digest 12:25, Kiani TRY
13:25, receive-toman calculator 14:25, Turkey FX 15:25, receive-TRY calculator
16:25, Iran FX 17:25, Iran gold 18:25, hawala 19:25. All times are Istanbul.
Total: 15 scheduled posts, plus conditional alerts, when sources pass validation.
Timers do not catch up missed runs. Reserved/ambiguous sends require manual
reconciliation before retrying; successful daily deliveries cannot repeat.

All non-gold formats end with the requested phrase. The two gold formats omit it.
The digest omits `تومان مگر موارد دلاری`. Official twitter-text 3.1.0 validates
NFC-normalized text, URL detection and weighted length before every X send.
Longer numbers first lose thousands separators. If a complete post still cannot
fit, it fails without sending; no prices, rows or mandatory footer are truncated.

The renderer reads only explicit numeric fields from existing Telegram formats.
A changed or incomplete upstream format is blocked and needs a formatter update.
Telegram pricing calculations and message content are unchanged. Market exports
require VERIFIED even if MARKET_SAFETY_MODE is off. Collection uses a temporary
SQLite backup to avoid changing production market history.

## Required before activation

1. Compare the package patch against BOTH the current GitHub default branch and
   the actual server working tree. The development branch is not evidence that
   the live checkout is identical. Use the included staging script; do not pull,
   reset, restore whole files, stash production edits, or merge the entire branch.
2. The server needs Python 3.11+ and Node 22 available on the service PATH.
   Install the locked validator with `npm ci --prefix x_text` in the staged
   candidate. Run the tests below before applying production changes.
3. Configure `/home/kianirad2020/.config/kiani-x.env` with the existing four
   X credentials, shared-pricing configuration needed by Telegram, and
   `X_HAWALA_SNAPSHOT`. Keep that file owner-readable only. Do not copy secrets
   into Git, the patch package or chat.
4. The inspected `hawala_runtime.py` applies shared database adjustment factors
   before calling the original calculator. The prepared `hawala-bridge.patch`
   exports the exact returned rates after a successful Telegram delivery.
   Set `X_HAWALA_SNAPSHOT` to the SAME absolute path in both the existing hawala
   service environment and the new X service environment. Use a directory owned
   by `kianirad2020`, such as `/home/kianirad2020/.local/state/kiani-x/hawala.json`.
   The atomic snapshot has this shape (values are examples only):

   ```json
   {"source":"kiani-hawala","generated_at":"2026-09-25T12:00:00+00:00",
    "rates":{"USD":229800,"EUR":261500,"GBP":304200,"CAD":162900,
             "AUD":161600,"SEK":23200,"TRY":4700}}
   ```

   The 19:45 Tehran Telegram slot is 19:15 Istanbul, ten minutes before the
   19:25 X slot. X rejects snapshots older than 15 minutes, so a missed Telegram
   slot cannot silently reuse the previous hour. This timestamp describes when
   the bot calculated the rates; it does not claim that cached upstream FX is
   fresh. The existing bot's FX-cache and pricing policies remain unchanged.

   Prepare a patch against the ACTUAL server file, without changing it:

   ```bash
   python3 channel_split/prepare_hawala_x_bridge.py /home/kianirad2020/kiani-hawala-bot/hawala_bot.py > /tmp/hawala-bridge-reviewed.patch
   ```

   This rejects a changed scheduler or an already installed hook. Inspect the
   diff, back up the actual file, and use `git apply --check` followed by
   `git apply` from `/home/kianirad2020/kiani-hawala-bot`. The patch changes only
   the successful-send path in `process_current_slot`; it does not modify the
   runtime wrapper, calculation, live factors, Telegram text or slot database.
   Install `channel_split/hawala_x_snapshot.py` with the repository patch first.
   Restart only the existing hawala service after its environment and hook are
   configured. Wait for the next normal successful Telegram slot; do not force
   a real send as a test. Confirm the snapshot exists, then run the X hawala dry-run.

## Validation

```bash
npm ci --prefix x_text
python3 -m unittest tests.test_x_daily_rates tests.test_x_channel_posts tests.test_x_export tests.test_hawala_x_bridge tests.test_channel_split_iran_fx_dolarchand tests.test_channel_split_daily_market_digest tests.test_channel_split_daily_digest_production tests.test_channel_split_kiani_posts -v
python3 x_daily_rates.py --dry-run --variant morning
python3 x_daily_rates.py --dry-run --mode alert --state-file /path/to/copied-alert-state.json
python3 x_channel_daily.py --post bank-comparison --dry-run
```

Repeat the last command for all eleven post names listed in `POST_TYPES` in
`x_channel_formats.py`, using the existing shared pricing configuration and
production history path. Live source verification can legitimately block posts;
do not weaken its thresholds. These dry runs do not send or reserve daily slots.

## Activation after server installation and live dry runs

Deploy the narrow GitHub workflow/script/validator changes to the default branch
through a reviewed patch. Existing Actions schedules run only from that branch.
Do not enable another scheduler for the four fixed posts or movement checks.

On the server, apply only the reviewed package patch, make
`/home/kianirad2020/.local/state/kiani-x` owned by the service user, then install
only `deploy/systemd/kiani-x-*.timer` and `kiani-x-channel@.service` into systemd.
Review `systemd-analyze verify` and `systemd-analyze calendar` before enabling
those exact eleven timers. No existing Telegram/hawala service needs restarting
for these new X units. Only the hawala service needs its narrowly scoped restart
to load the inspected snapshot hook and its environment setting.

Do not start individual services as a test: that publishes real posts. Enabling
the timers begins the next scheduled slots. Check journal output for each first
run and preserve the delivery SQLite file across updates and restarts.

## Rollback

Stop and disable only the eleven new `kiani-x-*.timer` units. Revert the reviewed
X workflow patch on the default branch if necessary. For local code, first use
`git apply --reverse --check` on the package patch; reverse it only if it still
applies cleanly. If later work overlaps, review a targeted reverse diff instead
of restoring whole files. Preserve X delivery state to avoid duplicate posts.
To disable hawala snapshot exports, unset `X_HAWALA_SNAPSHOT` in the hawala
service and restart only that service; the export hook is then inactive.

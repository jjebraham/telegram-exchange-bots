# AlanChande Telegram Referral Contest Bot

Dedicated referral/giveaway bot for [`@alanchande_com`](https://t.me/alanchande_com), intentionally isolated from the exchange bot.

## Owned-audience seed acquisition

Admins can run `/owned_sources [campaign_slug]` to compare `meditation_b`,
`kriptofarsi_b`, and `trstudy_b`, including sources with no traffic yet. It shows
tracked links, unique first-touch starts, new/returning classifications,
start-to-entry rates, link holders, holders with downstream opens, unique openers,
and joined/active/qualified referrals. `/sources` provides detailed auto-entry
diagnostics and sharing activation for all sources, split across messages.

Prepare each audience's post with the existing admin command:

```text
/promo_post meditation b
/promo_post kriptofarsi b
/promo_post trstudy b
```

These commands return drafts in the admin chat; they do not publish to channels.
Use the matching tracked link and preserve its source slug when posting. Promo
links and post drafts target the live campaign, even when viewing an older report.
No schema migration or campaign configuration is required.

Before acquisition, smoke-test existing-member auto-entry and non-member
channel-join auto-entry using fresh accounts. Save `/owned_sources` and `/sources`
baselines plus the UTC posting time, then launch one audience at a time. Compare
increments after the same elapsed time (for example, 24 hours), keeping sample
sizes visible. First-touch source is retained across repeat promo clicks;
historical referral trees remain legacy/untracked. Reports are campaign-to-date,
not isolated post-deploy or 24-hour cohorts. A holder's downstream open is not
proof of native Share completion. Telegram post views are not measured, so these
reports cannot calculate view-to-start rates. Zero starts means no measured
acquisition yet; a rate without a denominator is shown as `n/a`.

## Current design

- Persistent random bot deep-link per participant/campaign: `https://t.me/Alanchandebot?start=ref_...`
- First referrer is permanent inside a campaign.
- No self-referral.
- Referral attribution is reserved before the friend joins the public channel.
- Telegram `chat_member`, manual verification, reminders, and reconciliation can finalize a pending join.
- Leaving removes live credit; rejoin keeps the original referrer and restarts the retention clock.
- Default retention: **168 continuous hours / 7 days**.
- Default scoring: **2 active referrals = 1 temporary point**.
- Only retention-qualified referrals create **confirmed draw tickets**.
- Default cap: **20 confirmed tickets**.
- Live leaderboard ranks temporary score but clearly displays confirmed tickets separately.
- Participant welcome is idempotent and automatically gives referred users their own referral link.
- Funnel tracking supports `promo_SOURCE` deep links.
- A periodic reconciliation worker repairs unresolved pending joins and currently-left active referrals after missed Telegram events.
- Referral state changes and admin actions are append-only logged for audit/forensics.
- SQLite runs in WAL mode with busy timeout.
- Supervisor keeps one polling process alive.

## Important live-campaign protections

### Rules are locked after activation

`/campaign_config` is allowed only while a campaign is a draft. Activation sets `rules_locked_at`; scoring parameters cannot be silently changed mid-campaign.

### Fixed draw time and qualification cutoff

Each campaign stores an explicit `draw_at`. Existing databases are migrated automatically; old campaigns are backfilled with the previous policy: **21:00 Istanbul on the calendar day after campaign end**.

The final retention cutoff is fixed as:

```text
final_qualification_cutoff = draw_at - min_stay_hours
```

The final entrant set therefore does not change merely because an admin runs the draw late.

### Frozen entrant snapshot before entropy

At/after the fixed draw time, run:

```text
/snapshot paeez1405
```

The bot:

1. re-checks Telegram membership using the fixed draw-time qualification cutoff;
2. deactivates invalid/deleted/left qualified referrals;
3. verifies eligible entrants;
4. freezes the exact weighted entrant list;
5. stores and prints a SHA-256 digest.

Publish that digest before the seed/entropy exists.

### Externally verifiable seed

The draw no longer accepts an arbitrary admin-selected seed.

After `/snapshot`, wait for the **first Bitcoin block whose timestamp is after the snapshot time**. Then run:

```text
/draw paeez1405 | BITCOIN_BLOCK_HEIGHT | BITCOIN_BLOCK_HASH
```

The bot verifies via Blockstream that:

- the supplied hash belongs to the supplied height;
- the block timestamp is after the frozen snapshot;
- the previous Bitcoin block timestamp is before the frozen snapshot.

This enforces the first Bitcoin block after the snapshot as public future entropy. The weighted draw uses that block hash as the deterministic seed.

The same seeded run produces:

- the configured winners;
- up to 5 ordered reserve winners.

A disqualified winner can therefore be replaced by the next pre-committed reserve rather than by admin choice.

## User scoring vocabulary

The UI distinguishes:

```text
⭐ امتیاز موقت
🎟 بلیت تأییدشده
```

Temporary score is based on referrals who are active now. Confirmed tickets require the full retention period and are the only weight used in the final draw.

The stats screen also shows:

- active / qualified / pending / left referrals;
- unfinished referral-link opens;
- distance to the next temporary point;
- nearest qualification countdown;
- the participant's current leaderboard rank.

The leaderboard masks participant identities and explicitly states that leaderboard rank does **not** determine prize order.

## Late-referral disclosure

The bot calculates and displays the latest `stay_since` that can still finish the retention period by the fixed draw time. After that moment, new active referrals can still appear in temporary progress but are visibly marked as unable to become confirmed tickets in time for the draw.

## Trust / transparency menu

The main menu includes:

```text
🛡 شفافیت
```

It explains:

- scoring rules are locked after activation;
- membership is re-verified;
- entrant snapshot SHA-256 is published;
- Bitcoin future entropy determines the draw seed;
- winners and reserves come from one deterministic weighted draw;
- draw proof will include snapshot hash, seed source, result, and code version.

## Referral flow

```text
referrer shares personal bot deep link
        ↓
friend presses Start in @Alanchandebot
        ↓
first-referrer attribution is reserved
        ↓
friend opens @alanchande_com and presses Telegram's native Join button
        ↓
chat_member event OR manual check OR reconciliation confirms membership
        ↓
referral is finalized atomically
        ↓
referrer gets temporary progress immediately
        ↓
referred user gets congratulations + own referral link + menu
        ↓
continuous retention clock runs
        ↓
qualified referral creates confirmed draw weight
```

## Promo / funnel flow

Use tagged links such as:

```text
https://t.me/Alanchandebot?start=promo_bigchannel
https://t.me/Alanchandebot?start=promo_alphadl
```

Admin report:

```text
/funnel paeez1405
```

Tracked/derived stages include bot starts, entered-contest users, personal links, referral-link opens, candidates, joined referrals, active referrals, and qualified referrals.

Telegram does not expose channel post views or whether the native Share sheet was actually completed.

## Anti-fraud review

The current campaign does not auto-disqualify users using heuristics. The bot provides a flag-only report:

```text
/flags paeez1405
```

Current signals include high referral velocity, high leave ratio, and unusually high volume. These are review signals only.

Before payout, combine `/verify`, `/flags`, `/audit`, manual review, and winner contact. Do not auto-DQ a participant from one weak heuristic.

## Admin audit

Admin campaign/draw actions are written to `admin_audit_log`.

```text
/adminlog
/adminlog paeez1405
```

## Campaign commands

Create a draft:

```text
/campaign_create autumn26 | Autumn Giveaway | 2026-09-20T00:00:00+03:00 | 2026-10-20T23:59:59+03:00 | prize text
```

Configure **before activation only**:

```text
/campaign_config autumn26 | 2 | 168 | 20 | 5
```

Optional explicit draw time while still draft:

```text
/campaign_draw_at autumn26 | 2026-10-21T21:00:00+03:00
```

Activate:

```text
/campaign_activate autumn26
```

Other admin commands:

```text
/campaigns
/stats paeez1405
/funnel paeez1405
/audit USER_ID paeez1405
/flags paeez1405
/adminlog paeez1405
/verify paeez1405
/snapshot paeez1405
/draw paeez1405 | BITCOIN_BLOCK_HEIGHT | BITCOIN_BLOCK_HASH
```

## Reconciliation

Defaults:

```text
PENDING_REMINDER_MINUTES=15
PENDING_REMINDER_CHECK_SECONDS=300
RECONCILIATION_CHECK_SECONDS=21600
RECONCILIATION_BATCH_SIZE=200
QUALIFICATION_CHECK_SECONDS=3600
```

The reminder is one-time, but reconciliation continues to inspect unresolved pending referrals even after a reminder was already sent. This closes the previous gap where a user could join after their reminder while the membership event was missed.

Active referrals are also rechecked in a bounded batch to heal currently-left membership state after missed events. A leave+rejoin sequence that happens entirely between checks cannot be reconstructed from the Bot API; the event history/reconciliation substantially reduces, but cannot eliminate, that Telegram limitation.

## SQLite backup

A safe online backup utility is included:

```bash
cd /home/kianirad2020/telegram_bot_repo/alanchande-referral-bot
set -a
source .env
set +a
BACKUP_DIR=/home/kianirad2020/alanchande-backups \
  .venv/bin/python scripts/backup_db.py
```

It uses SQLite's backup API, writes a SHA-256 manifest, and removes backups older than `BACKUP_RETENTION_DAYS` (default 30).

For real disaster recovery, sync `BACKUP_DIR` to another host/object store or use a separately mounted remote destination. A backup on the same server is not an off-site backup.

## Supervisor

Production must run exactly one polling process for this token.

```bash
sudo supervisorctl status alanchande_referral_bot
sudo supervisorctl restart alanchande_referral_bot
```

Do not run `.venv/bin/python bot.py` manually at the same time as Supervisor.

## Production update

```bash
cd /home/kianirad2020/telegram_bot_repo/alanchande-referral-bot || exit 1

git pull --ff-only origin feature/alanchande-referral-bot-20260914

.venv/bin/python -m unittest discover -s tests -v

sudo supervisorctl restart alanchande_referral_bot
sudo supervisorctl status alanchande_referral_bot
```

The DB migration runs automatically during bot initialization and is additive.

## Tests / CI

```bash
.venv/bin/python -m unittest discover -s tests -v
```

GitHub Actions compiles the project and runs the full test suite on Python 3.10 and 3.12.

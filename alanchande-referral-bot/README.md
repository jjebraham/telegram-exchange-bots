# AlanChande Telegram Referral Contest Bot

Dedicated referral/giveaway bot for [`@alanchande_com`](https://t.me/alanchande_com).
It is intentionally separate from `@kianiexchangebot`, so referral traffic, restarts,
database changes, and giveaway code cannot interfere with the exchange bot.

## What it does

- Gives each participant a **persistent invite link per campaign**.
- Attributes joins from the exact Telegram invite link used.
- Requires a configurable **continuous stay** before a referral is qualified.
  Default: **168 hours / 7 days**.
- If the referred member leaves, their credit disappears. If they rejoin during
  the active campaign, the original referrer is kept and the stay timer restarts.
- One Telegram account can be attributed only once per campaign.
- Shows users their qualified/pending/left referrals, points, personal link,
  leaderboard, prizes, and rules in Persian.
- Uses **2 qualified referrals = 1 point** by default.
- Uses a default **20-point cap** to reduce referral farming.
- Sends a notification when a referral becomes qualified.
- Supports multiple historical campaigns without mixing their referrals.
- Runs a deterministic **weighted random draw without replacement**.
- Before drawing, re-checks both qualified referred users and entrants against
  Telegram channel membership.
- Stores the entrant snapshot, public seed, winners, verification summary, and a
  SHA-256 digest for auditability.

## Important Telegram requirements

1. Create a **new dedicated bot** with `@BotFather`.
2. Add the bot as an **administrator** of `@alanchande_com`.
3. Give it permission to **invite users via link**.
4. Use the numeric channel ID (`-100...`) for `CHANNEL_ID` when possible.
5. The bot uses polling with `allowed_updates=Update.ALL_TYPES`, which is required
   for `chat_member` updates.
6. Do **not** run two polling processes with the same bot token.

A public-channel join through search or the public `t.me/alanchande_com` URL has no
referrer. Only a join through a personal invite link can create new attribution.

## Install

```bash
cd /home/kianirad2020/telegram_bot_repo/telegram-exchange-bots/alanchande-referral-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Export the environment variables through Supervisor/systemd/Docker rather than
`source .env` in production. Never commit the real token.

For a quick shell test:

```bash
export BOT_TOKEN='...'
export CHANNEL_ID='-100...'
export CHANNEL_URL='https://t.me/alanchande_com'
export ADMIN_IDS='YOUR_TELEGRAM_ID'
export DB_PATH="$PWD/referral_bot.db"
.venv/bin/python bot.py
```

## Create the first campaign

Admin commands are accepted only from Telegram IDs in `ADMIN_IDS`.
Dates **must include a timezone offset**. Istanbul is `+03:00`.

Create a draft campaign:

```text
/campaign_create autumn26 | AlanChande Autumn Giveaway | 2026-09-20T00:00:00+03:00 | 2026-10-20T23:59:59+03:00 | 5 prizes - details announced in the channel
```

Optional: change scoring before launch:

```text
/campaign_config autumn26 | 2 | 168 | 20 | 5
```

This means:

- 2 qualified referrals = 1 point
- 168 continuous hours = 7-day qualification period
- max 20 points/tickets per participant
- 5 winners

Activate it:

```text
/campaign_activate autumn26
```

See campaigns and stats:

```text
/campaigns
/stats autumn26
/audit 123456789 autumn26
```

Close new referral activity before the draw:

```text
/campaign_close autumn26
```

Run final membership verification:

```text
/verify autumn26
```

Then draw using a **publicly announced seed**:

```text
/draw autumn26 | PUBLIC-SEED-HERE
```

The command refuses to draw if Telegram membership verification has errors, if
there are fewer eligible entrants than winners, or if the campaign was already
drawn.

## Suggested Telegram channel greeting

Use the channel greeting/pinned CTA to send new members into the dedicated bot:

> 🎁 **با معرفی دوستانت جایزه ببر!**
>
> هر ۲ دوستی که با لینک اختصاصی تو عضو کانال شوند و حداقل ۷ روز عضو بمانند،
> ۱ امتیاز برای قرعه‌کشی می‌گیری.
>
> هرچه امتیاز بیشتری داشته باشی، شانس برنده شدنت بیشتر است.
>
> 👇 برای گرفتن لینک اختصاصی و دیدن امتیازها، ربات مسابقه را شروع کن.

Button URL:

```text
https://t.me/YOUR_NEW_BOT_USERNAME?start=channel
```

The user must press **Start** because Telegram bots cannot initiate a private chat
with a user who has never contacted the bot.

## User menu

The Persian user interface contains:

- 📤 دعوت دوستان
- 📊 امتیازهای من
- 👥 دعوت‌های من
- 🏆 جدول مسابقه
- 🎁 جوایز
- 📜 قوانین
- 📢 کانال الان چنده؟

The invite screen includes a Telegram **share button**, so the user does not need
to manually copy the personal link.

## Anti-abuse behavior

A referral progresses as:

```text
join with personal link
        ↓
pending for 7 continuous days
        ↓
qualified
        ↓
leaves channel → credit stops counting
        ↓
rejoins during active campaign → original referrer kept, 7-day timer restarts
```

Additional controls:

- no self-referral
- first referrer is permanent within a campaign
- one referred Telegram ID per campaign
- point cap
- final membership verification before draw
- entrant must still be a member at draw time
- admin `/audit` command

Telegram does not provide bots with a trustworthy "account creation date" or a way
to prove that two accounts are actually friends, so those should not be used as
anti-fraud rules.

## Supervisor

Copy `deploy/supervisor.conf.example`, replace the token/channel/admin values, then:

```bash
sudo cp deploy/supervisor.conf.example /etc/supervisor/conf.d/alanchande_referral_bot.conf
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start alanchande_referral_bot
sudo supervisorctl status alanchande_referral_bot
```

Do not put the real token into GitHub.

## Tests

Core tests require only Python:

```bash
PYTHONPATH=. python3 -m unittest -v tests.test_core
```

Full tests require the Telegram dependency:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

GitHub Actions runs compilation and the full test suite on Python 3.10 and 3.12.

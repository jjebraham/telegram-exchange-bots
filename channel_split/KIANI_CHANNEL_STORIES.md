# Daily Kiani channel stories

The successful **12:10 Istanbul** `kiani-rates` photo from @exchangekiani is shared
to stories on **@alanchande_com and @exchangekiani**, with a native link back to
the source post and the three channel handles. The complete photo is fitted on
a 1080×1920 canvas without cropping. No rates are fetched or recalculated.

The timer checks each minute from 12:10:30 through 12:29:30 Istanbul. It only
accepts a same-day successful publisher receipt in the 12:10 slot, and verifies
the actual Telegram photo and timestamp before sending. Missing/failed posts
are skipped; earlier hours and yesterday's rates are never substituted.

## One-time private administrator login

Use the Telegram **Premium administrator account that manages both channels**.
It needs permission to post stories, and both channels need enough boosts and
available story capacity. Telegram documents these requirements in
[canSendStory](https://core.telegram.org/method/stories.canSendStory) and
[sendStory](https://core.telegram.org/method/stories.sendStory).

1. Open [Telegram API applications](https://my.telegram.org/apps) privately and
   obtain your application API ID and API hash. These are different from a bot
   token. If creating an application, choose a descriptive app name and use
   Telegram's application form.
2. In your own server terminal, run the installed `setup_kiani_stories.py` using
   the dedicated story virtual environment. Enter the API ID/hash and your
   administrator phone number, login code and two-step password when asked.
   The hash, code and password prompts are hidden. **Do not paste any of these
   values or session files into chat.**
3. Setup checks the account and both channels. `READY` means the next successful
   daily source post may be shared. Setup itself publishes no story. If a
   permission/boost/capacity check fails, the readiness marker stays absent.

Interactive login allows two bounded SDK retries so Telegram can redirect it
to the account's data center. The publishing worker keeps zero automatic
request retries. Telegram flood waits are surfaced immediately in setup;
neither login codes nor credentials are included in error messages. If setup
stops, rerun the same command privately; saved application details are reused.

Configuration and account login are stored privately in
`~/.config/kiani-stories/` and `~/.local/share/kiani-stories/`, with owner-only
access. The login persists; it is not required every day. Telegram sessions
[contain account credentials](https://docs.telethon.dev/en/stable/concepts/sessions.html).

Recheck the approved login with `setup_kiani_stories.py --check`. After fixing
boosts or permissions, a successful recheck restores readiness. Revoking the
session in Telegram Settings → Devices also revokes the worker's login.

## Exact expiry and delivery receipts

Every send requests `period=172800` and `pinned=False`; there is no 24-hour
fallback. The returned expiry must be exactly 48 hours. An incorrect expiry
returned directly for a newly created story is removed and that target is
blocked for the day. Existing unrelated stories are never removed.

The independent private delivery database records each day, target, source
message, stable request ID and resulting story ID. A second run never resends
a confirmed story. Lost responses are reconciled against the native source
post link; an ambiguous send is held for review instead of blindly repeated.
Telegram flood wait periods are persisted and observed across both targets.

The receipt table is read-only. Existing publisher timers, prices, bot tokens,
normal posts and the existing daily channel forward are unchanged.

## Installation and rollback

Install `requirements-stories.txt` into a separate virtual environment, run
`test_kiani_stories.py`, then run `install_kiani_stories.py` as the publishing
account with `--project-dir` and `--venv`. It backs up only the story code and
units, installs the dedicated service/timer and enables the timer. The service
requires the private `ready` marker, so it cannot publish before setup succeeds.

Inspect with `systemctl status kiani-channel-stories.timer` and
`journalctl -u kiani-channel-stories.service`. Logs contain delivery statuses
and error categories, never login credentials. Stop future stories with
`sudo systemctl disable --now kiani-channel-stories.timer`; normal channel
publishing continues. Removing the private `ready` marker also pauses stories.
Stopping the timer does not delete already-published stories.

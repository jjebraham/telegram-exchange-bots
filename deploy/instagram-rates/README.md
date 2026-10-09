# Daily Instagram publisher credential setup

For the new daily Feed carousel, see [CAROUSEL.md](CAROUSEL.md). The existing
Selenium cron remains 11:30 Istanbul and the Story keeps its current rate card.

The Selenium cron job runs at `30 8 * * *` on a UTC server: 11:30 in
`Europe/Istanbul`. It runs `~/publish-kiani-instagram-rates.sh publish`, which
loads `~/.kiani-instagram.env` and publishes the Story and Feed separately.

An OAuth error with code 190 and subcode 463 means the saved credential expired.
Generating another short-lived Explorer token only restores publishing for its
short lifetime. Configure the Page token once using the helper below.

## One-time setup on Selenium

1. In Graph API Explorer, select the same Meta app used for Instagram and
   generate a fresh **User Token**. Grant `pages_show_list`, `instagram_basic`,
   `instagram_content_publish`, and `pages_read_engagement`, including access to
   the Kiani Facebook Page. The helper accepts a User Token as its input.
2. Have that app's App ID and App Secret available locally.
3. Run `python3 deploy/instagram-rates/setup_long_lived_token.py` as
   `kianirad2020`. Its default environment file is `~/.kiani-instagram.env`.

The helper prompts for the credentials without echoing the secret or token. It
exchanges the User Token, retrieves the token for Page `1287244881149876`,
checks its app, type, validity, linked Instagram account `17841411127622820`,
publishing scope, and actual expiry through Meta's API, then verifies Instagram
account access. It only installs a Page token for which `expires_at` is zero.

After validation, it creates a private backup and atomically replaces only
`INSTAGRAM_ACCESS_TOKEN`, with mode 0600. It preserves the environment's other
settings. The App Secret and intermediate User Tokens are not saved. The helper
does not publish media or change the cron schedule.

If the token still has a fixed expiry, the helper stops without replacing the
credential. It also reports any data-access deadline returned by Meta. A token
without a fixed expiry can still be invalidated by Meta or by changes to the
account, app, or Page permissions; those cases require reauthorization.

## Catch up a failed scheduled run

After the helper succeeds, run:

```bash
~/publish-kiani-instagram-rates.sh publish
```

The wrapper uses its normal per-mode daily duplicate protection. Successful
scheduled runs use the new token automatically; no cron restart is necessary.
Avoid forcing a retry unless a second publication is intentional.

Read the scheduled run output with:

```bash
tail -n 100 ~/kiani-instagram-cron.log
```

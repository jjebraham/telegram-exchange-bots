# AlanChande image publisher rollout

This branch adds dynamic, deterministic Persian/RTL PNG cards for five existing validated posts:
- alanchande-usdt-exchanges
- alanchande-iran-fx
- alanchande-iran-gold
- alanchande-turkey-gold
- alanchande-fx-pulse

Rates continue to come from the existing producer. The renderer parses its already-validated output, so sample illustrations never become production prices. Existing MARKET_SAFETY_MODE, publish history, and scheduled services are preserved.

## GitHub Actions

Run the workflow **AlanChande image publisher** at:
https://github.com/jjebraham/telegram-exchange-bots/actions/workflows/alanchande-image-posts.yml

Select one of:
- test-only: runs all five data, formatting, RTL screenshot tests on a GitHub-hosted runner; does not access your server.
- preview: runs the tests, uploads selected code to Google Cloud 34.19.54.235 using SSH, verifies that the live publisher has the expected integration anchors, installs the opt-in renderer, generates data-validated previews and uploads them to **@alanchandetest**. The production channel remains in text mode.
- activate: does everything in preview and then atomically sets ALANCHANDE_POST_FORMAT=image in the production server's protected channel_split/.env. Next existing scheduled AlanChande posts publish photos; Kiani and other messages remain text.

## Repository Secrets

Create these under **Settings > Secrets and variables > Actions**:

1. **ALANCHANDE_DEPLOY_SSH_KEY** — private Ed25519 key authorized for kianirad2020@34.19.54.235. Never commit or paste it into issues or chat.
2. **ALANCHANDE_DEPLOY_KNOWN_HOSTS** — verified SSH server public host key line for 34.19.54.235 (not an unverified fingerprint).

Do not put Telegram bot tokens in GitHub. The runner triggers an SSH command; the Telegram bot token remains in the server's protected channel_split/.env.

## Server prerequisites

- /usr/bin/python3 must import playwright.sync_api.
- A Chromium executable or Playwright-managed Chromium must be available to that Python user.
- A Persian-capable font, ideally Noto Sans Arabic or Vazirmatn.
- Existing channel_split/run_channel_split_production.sh, systemd units, and post safety scripts must remain configured.
- The bot must be able to post to @alanchandetest before preview is run.

The deployment fails closed if the production file does not match expected code anchors or if the rendering/data-safety checks fail. It never runs git pull, git reset or git clean on the server.

## Rollback

On the server, edit channel_split/.env to set ALANCHANDE_POST_FORMAT=text. New oneshot publisher runs return to text. The installer also saves the previous publish_channels.py under ~/kiani-image-backups/<timestamp>/.

## Limitations

- Existing Iran gold, Turkish gold, and FX-pulse messages do not supply one-month history; the template shows "—" for missing Δ1M.
- Historical prices in tests are sample-only and should never be sent as live market quotes.
- The HTTP parser consumes the currently approved text payload and must be regression-tested when the upstream text format changes.
- Do not activate without checking the five test-channel images and ensuring buy/sell semantics match the official rates.

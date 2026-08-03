# Shared pricing admin integration for `main_user_bot`

The unified panel at `https://peerexo.com/alanchande/` stores all percentages in:

```text
/home/kianirad2020/send_changes/pricing_settings.db
```

The production bot is currently outside this repository at:

```text
/home/kianirad2020/telegram_bot/main_user_bot.py
```

For that reason this integration does **not** overwrite the production file. `main_user_runtime.py` reads the file, strictly replaces the reviewed hard-coded price multipliers in memory, compiles the transformed program, and starts its existing async `main()` function.

## Controlled settings

The wrapper reads these settings immediately whenever a user requests a rate:

- `user_tl_buy_adjustment_pct` — default `+2.00%`
- `user_tl_sell_adjustment_pct` — default `-3.00%`
- `user_usdt_buy_adjustment_pct` — default `+1.00%`
- `user_usdt_sell_adjustment_pct` — default `-1.00%`
- `user_try_to_usdt_adjustment_pct` — default `+2.00%`
- `user_usdt_to_try_adjustment_pct` — default `-2.00%`

These defaults preserve the current calculations in the tracked `main_user_bot_clone.py`.

## Mandatory production compatibility check

Copy these two reviewed files to the production directory:

```bash
cp main_user_pricing_client.py /home/kianirad2020/telegram_bot/
cp main_user_runtime.py /home/kianirad2020/telegram_bot/
```

Then run the strict check using the same Python environment as Supervisor:

```bash
cd /home/kianirad2020/telegram_bot
MAIN_USER_BOT_SOURCE=/home/kianirad2020/telegram_bot/main_user_bot.py \
PRICING_DB_PATH=/home/kianirad2020/send_changes/pricing_settings.db \
/usr/bin/python3 main_user_runtime.py --check
```

Expected result:

```text
OK: patched and compiled 13 pricing handlers from /home/kianirad2020/telegram_bot/main_user_bot.py
```

If the command fails, do **not** change Supervisor. The failure means the running file differs from the reviewed clone and needs a targeted review first.

## Supervisor change after a successful check

Find the existing `[program:main_user_bot]` configuration and change only its command to:

```ini
command=/usr/bin/python3 /home/kianirad2020/telegram_bot/main_user_runtime.py
```

Add these environment values to the same program:

```ini
environment=MAIN_USER_BOT_SOURCE="/home/kianirad2020/telegram_bot/main_user_bot.py",PRICING_DB_PATH="/home/kianirad2020/send_changes/pricing_settings.db"
```

Preserve all existing Supervisor options and existing environment variables. Then apply:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl restart main_user_bot
sudo supervisorctl status main_user_bot
```

## Rollback

Restore the original Supervisor command:

```ini
command=/usr/bin/python3 /home/kianirad2020/telegram_bot/main_user_bot.py
```

Then reread, update, and restart the program. The original bot file is never modified by this integration.

## Security warning

The public repository currently contains credentials in `main_user_bot_clone.py`. Rotate every exposed Telegram token, API key, proxy credential, and third-party token, move them to environment variables, and purge them from Git history before treating this repository as secure.

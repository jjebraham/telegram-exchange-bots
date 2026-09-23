#!/usr/bin/env python3
"""Read-only verification of the running Hawala bot's current and target channels.

Run using /home/kianirad2020/kiani-hawala-bot/.venv/bin/python.
Reads only the active process's environment; never prints bot tokens.
Makes only Telegram getMe/getChat/getChatMember API calls. Sends no messages.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def active_hawala_environment() -> dict[str, str]:
    matches: list[dict[str, str]] = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ")
            if b"/kiani-hawala-bot/hawala_runtime.py" not in cmdline:
                continue
            raw = (proc / "environ").read_bytes().split(b"\0")
            env = {
                key.decode("utf-8", "replace"): value.decode("utf-8", "replace")
                for item in raw if b"=" in item
                for key, value in [item.split(b"=", 1)]
            }
            matches.append(env)
        except (OSError, ValueError):
            continue
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one readable running Hawala process; "
            f"found {len(matches)}. Do not switch channels yet."
        )
    return matches[0]


def main() -> int:
    import telebot  # Imported from the existing Hawala bot's own venv.

    env = active_hawala_environment()
    secret_candidates = (
        "TELEGRAM_BOT_TOKEN", "BOT_TOKEN", "HAWALA_BOT_TOKEN"
    )
    token = next((env.get(key) for key in secret_candidates if env.get(key)), None)
    if not token:
        extra_keys = sorted(
            key for key in env if key.endswith("_BOT_TOKEN") and env.get(key)
        )
        if len(extra_keys) == 1:
            token = env[extra_keys[0]]
    source = env.get("TELEGRAM_CHANNEL_ID")
    if not token or not source:
        raise RuntimeError(
            "Cannot read active bot token/channel from process environment. "
            "Do not disclose tokens or switch the publisher."
        )
    stage = "initialize Telegram client"
    try:
        # Mirror the legacy bot's optional Telegram transport proxy.
        if env.get("PROXY_URL"):
            telebot.apihelper.proxy = {"https": env["PROXY_URL"]}
        bot = telebot.TeleBot(token, threaded=False)
        stage = "getMe (identify current Hawala bot)"
        me = bot.get_me()
        print(f"Bot identity: @{me.username}")
        stage = "getChat (current configured channel)"
        current = bot.get_chat(int(source) if source.lstrip("-").isdigit() else source)
        print(f"Current destination: {current.id} @{current.username or '(private)'}")
        stage = "getChat (@ExchangeKiani)"
        target = bot.get_chat("@ExchangeKiani")
        print(f"Target: {target.id} @{target.username or '(private)'}")
        stage = "getChatMember (target posting permission)"
        membership = bot.get_chat_member(target.id, me.id)
    except Exception as exc:
        # Do not print exception messages: URLs and some network errors can
        # include credentials. Stage and numeric HTTP code are sufficient.
        print(f"PREFLIGHT: FAILED at {stage}.")
        print(f"Exception type: {type(exc).__name__}")
        error_code = getattr(exc, "error_code", None)
        if isinstance(error_code, int):
            print(f"Telegram error code: {error_code}")
        print("No messages were sent and no configuration was changed.")
        return 1

    status = str(membership.status)
    can_post = (
        status == "creator"
        or (status == "administrator"
            and getattr(membership, "can_post_messages", False) is True)
    )
    print(f"Bot: @{me.username}")
    print(f"Current: {current.id} @{current.username or '(private)'}")
    print(f"Target: {target.id} @{target.username or '(private)'}")
    print(f"Target type: {target.type}")
    print(f"Bot role in target: {status}")
    print(f"Can post to target: {'YES' if can_post else 'NO'}")
    if target.type != "channel" or not can_post:
        print("PREFLIGHT: NOT READY. Add this bot as a posting admin first.")
        return 1
    if current.id == target.id:
        print("PREFLIGHT: current publisher already points to target.")
    else:
        print("PREFLIGHT: READY. Current and target channels are distinct.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

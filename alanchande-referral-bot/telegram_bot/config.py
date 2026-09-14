from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from telegram import ChatMemberUpdated
from telegram.constants import ChatMemberStatus

log = logging.getLogger("alanchande_referral_bot")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    channel_id_raw: str
    channel_url: str
    admin_ids: frozenset[int]
    db_path: str
    qualification_check_seconds: int = 3600
    default_invites_per_point: int = 2
    default_min_stay_hours: int = 168
    default_max_points: int = 20
    default_num_winners: int = 5

    @property
    def channel_ref(self) -> int | str:
        raw = self.channel_id_raw.strip()
        try:
            return int(raw)
        except ValueError:
            return raw if raw.startswith("@") else f"@{raw}"

    @property
    def channel_numeric_id(self) -> int | None:
        try:
            return int(self.channel_id_raw.strip())
        except ValueError:
            return None

    @property
    def channel_username(self) -> str | None:
        if self.channel_numeric_id is not None:
            return None
        return self.channel_id_raw.strip().lstrip("@").lower() or None

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.environ.get("BOT_TOKEN", "").strip()
        channel_id = os.environ.get("CHANNEL_ID", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is required")
        if not channel_id:
            raise RuntimeError("CHANNEL_ID is required; numeric -100... is recommended")

        def int_env(name: str, default: int, minimum: int = 0) -> int:
            raw = os.environ.get(name, "").strip()
            try:
                value = int(raw) if raw else default
            except ValueError:
                log.warning("Invalid %s=%r; using %s", name, raw, default)
                value = default
            return max(minimum, value)

        admins = frozenset(
            int(item.strip()) for item in os.environ.get("ADMIN_IDS", "").split(",")
            if item.strip().lstrip("-").isdigit()
        )
        return cls(
            bot_token=token,
            channel_id_raw=channel_id,
            channel_url=os.environ.get("CHANNEL_URL", "https://t.me/alanchande_com").strip(),
            admin_ids=admins,
            db_path=os.environ.get("DB_PATH", "referral_bot.db").strip(),
            qualification_check_seconds=int_env("QUALIFICATION_CHECK_SECONDS", 3600, 300),
            default_invites_per_point=int_env("DEFAULT_INVITES_PER_POINT", 2, 1),
            default_min_stay_hours=int_env("DEFAULT_MIN_STAY_HOURS", 168, 0),
            default_max_points=int_env("DEFAULT_MAX_POINTS", 20, 0),
            default_num_winners=int_env("DEFAULT_NUM_WINNERS", 5, 1),
        )


def is_configured_channel(chat, settings: Settings) -> bool:
    if chat is None:
        return False
    if settings.channel_numeric_id is not None:
        return chat.id == settings.channel_numeric_id
    return (getattr(chat, "username", None) or "").lower() == settings.channel_username


def extract_status_change(cmu: ChatMemberUpdated) -> tuple[bool, bool]:
    old, new = cmu.old_chat_member, cmu.new_chat_member
    statuses = {ChatMemberStatus.MEMBER, ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}
    was_member = old.status in statuses or (
        old.status == ChatMemberStatus.RESTRICTED and bool(getattr(old, "is_member", False))
    )
    is_member = new.status in statuses or (
        new.status == ChatMemberStatus.RESTRICTED and bool(getattr(new, "is_member", False))
    )
    return was_member, is_member


def chat_member_is_active(member) -> bool:
    if member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}:
        return True
    return member.status == ChatMemberStatus.RESTRICTED and bool(getattr(member, "is_member", False))


async def telegram_membership(bot, settings: Settings, user_id: int) -> bool:
    member = await bot.get_chat_member(settings.channel_ref, user_id)
    return chat_member_is_active(member)


def hours_label(hours: int) -> str:
    if hours and hours % 24 == 0:
        return f"{hours // 24} روز"
    return f"{hours} ساعت"


def remaining_label(seconds: int) -> str:
    if seconds <= 0:
        return "کمتر از یک ساعت"
    hours = (seconds + 3599) // 3600
    days, rem = divmod(hours, 24)
    if days and rem:
        return f"{days} روز و {rem} ساعت"
    return f"{days} روز" if days else f"{hours} ساعت"

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import timedelta

from telegram import ChatMemberUpdated
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

log = logging.getLogger("alanchande_referral_bot")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    channel_id_raw: str
    channel_url: str
    admin_ids: frozenset[int]
    db_path: str
    qualification_check_seconds: int = 3600
    pending_reminder_minutes: int = 15
    pending_reminder_check_seconds: int = 300
    reconciliation_check_seconds: int = 21600
    reconciliation_batch_size: int = 200
    analytics_snapshot_seconds: int = 3600
    nudge_check_seconds: int = 3600
    zero_referral_nudge_hours: int = 24
    promo_abandon_nudge_hours: int = 3
    notification_window_seconds: int = 600
    notification_max_per_window: int = 5
    daily_digest_hour_istanbul: int = 21
    daily_digest_check_seconds: int = 3600
    telegram_retry_attempts: int = 4
    telegram_retry_base_seconds: int = 1
    backup_dir: str = ""
    backup_rclone_dest: str = ""
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

        def int_env(name: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
            raw = os.environ.get(name, "").strip()
            try:
                value = int(raw) if raw else default
            except ValueError:
                log.warning("Invalid %s=%r; using %s", name, raw, default)
                value = default
            value = max(minimum, value)
            if maximum is not None:
                value = min(maximum, value)
            return value

        admins = frozenset(
            int(item.strip()) for item in os.environ.get("ADMIN_IDS", "").split(",")
            if item.strip().lstrip("-").isdigit()
        )
        db_path = os.environ.get("DB_PATH", "referral_bot.db").strip()
        default_backup_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
        return cls(
            bot_token=token,
            channel_id_raw=channel_id,
            channel_url=os.environ.get("CHANNEL_URL", "https://t.me/alanchande_com").strip(),
            admin_ids=admins,
            db_path=db_path,
            qualification_check_seconds=int_env("QUALIFICATION_CHECK_SECONDS", 3600, 300),
            pending_reminder_minutes=int_env("PENDING_REMINDER_MINUTES", 15, 1),
            pending_reminder_check_seconds=int_env("PENDING_REMINDER_CHECK_SECONDS", 300, 60),
            reconciliation_check_seconds=int_env("RECONCILIATION_CHECK_SECONDS", 21600, 900),
            reconciliation_batch_size=int_env("RECONCILIATION_BATCH_SIZE", 200, 10),
            analytics_snapshot_seconds=int_env("ANALYTICS_SNAPSHOT_SECONDS", 3600, 900),
            nudge_check_seconds=int_env("NUDGE_CHECK_SECONDS", 3600, 900),
            zero_referral_nudge_hours=int_env("ZERO_REFERRAL_NUDGE_HOURS", 24, 1),
            promo_abandon_nudge_hours=int_env("PROMO_ABANDON_NUDGE_HOURS", 3, 1),
            notification_window_seconds=int_env("NOTIFICATION_WINDOW_SECONDS", 600, 60),
            notification_max_per_window=int_env("NOTIFICATION_MAX_PER_WINDOW", 5, 1),
            daily_digest_hour_istanbul=int_env("DAILY_DIGEST_HOUR_ISTANBUL", 21, 0, 23),
            daily_digest_check_seconds=int_env("DAILY_DIGEST_CHECK_SECONDS", 3600, 900),
            telegram_retry_attempts=int_env("TELEGRAM_RETRY_ATTEMPTS", 4, 1),
            telegram_retry_base_seconds=int_env("TELEGRAM_RETRY_BASE_SECONDS", 1, 1),
            backup_dir=os.environ.get("BACKUP_DIR", default_backup_dir).strip(),
            backup_rclone_dest=os.environ.get("BACKUP_RCLONE_DEST", "").strip(),
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


def _retry_after_seconds(exc: RetryAfter) -> float:
    value = exc.retry_after
    if isinstance(value, timedelta):
        return max(0.0, value.total_seconds())
    return max(0.0, float(value))


async def telegram_membership(bot, settings: Settings, user_id: int) -> bool:
    """Rate-limit-aware membership lookup used by all critical verification paths."""
    attempts = max(1, settings.telegram_retry_attempts)
    for attempt in range(attempts):
        try:
            member = await bot.get_chat_member(settings.channel_ref, user_id)
            return chat_member_is_active(member)
        except (BadRequest, Forbidden):
            raise
        except RetryAfter as exc:
            if attempt == attempts - 1:
                raise
            delay = _retry_after_seconds(exc) + 0.25
            log.warning("Telegram rate limit for membership user=%s; retrying in %.2fs", user_id, delay)
            await asyncio.sleep(delay)
        except NetworkError:
            if attempt == attempts - 1:
                raise
            delay = settings.telegram_retry_base_seconds * (2 ** attempt)
            log.warning("Telegram network error for membership user=%s; retrying in %ss", user_id, delay)
            await asyncio.sleep(delay)
        except TelegramError:
            if attempt == attempts - 1:
                raise
            delay = settings.telegram_retry_base_seconds * (2 ** attempt)
            log.exception("Telegram membership error user=%s; retrying in %ss", user_id, delay)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable membership retry state")


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

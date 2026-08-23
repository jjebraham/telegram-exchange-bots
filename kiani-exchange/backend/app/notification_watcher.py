import asyncio
import logging

from .database import get_db
from .api.profile import ensure_profile_schema
from .user_notification import send_user_message

logger = logging.getLogger(__name__)


def _ensure_state_schema() -> None:
    ensure_profile_schema()
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_notification_state (
                event_key TEXT PRIMARY KEY,
                last_value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


async def _process_event(event_key: str, value: str, user_id: int, message: str) -> None:
    with get_db() as conn:
        state = conn.execute(
            "SELECT last_value FROM user_notification_state WHERE event_key = ?",
            (event_key,),
        ).fetchone()
        if not state:
            conn.execute(
                "INSERT INTO user_notification_state (event_key, last_value) VALUES (?, ?)",
                (event_key, value),
            )
            return
        if state["last_value"] == value:
            return

    sent = await send_user_message(user_id, message)
    if sent:
        with get_db() as conn:
            conn.execute(
                """UPDATE user_notification_state
                   SET last_value = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE event_key = ?""",
                (value, event_key),
            )


async def scan_user_notifications() -> None:
    _ensure_state_schema()
    with get_db() as conn:
        transactions = conn.execute(
            """SELECT t.id, t.user_id, t.reference_number, t.status
               FROM transactions t
               JOIN users u ON u.id = t.user_id
               WHERE u.telegram_chat_id IS NOT NULL"""
        ).fetchall()
        kyc_rows = conn.execute(
            """SELECT k.id, k.user_id, k.level, k.status, k.rejection_reason
               FROM kyc_submissions k
               JOIN users u ON u.id = k.user_id
               WHERE u.telegram_chat_id IS NOT NULL"""
        ).fetchall()

    for row in transactions:
        await _process_event(
            f"order:{row['id']}",
            str(row["status"]),
            int(row["user_id"]),
            f"📌 وضعیت سفارش #{row['reference_number']} تغییر کرد:\n{row['status']}",
        )

    for row in kyc_rows:
        status = str(row["status"])
        reason = str(row["rejection_reason"] or "").strip()
        if status == "approved":
            message = f"✅ سطح {row['level']} احراز هویت شما تایید شد."
        elif status == "rejected":
            message = f"❌ سطح {row['level']} احراز هویت شما رد شد."
            if reason:
                message += f"\nدلیل: {reason}"
            message += "\nمی‌توانید مدارک را دوباره ارسال کنید."
        else:
            message = f"📌 وضعیت احراز هویت سطح {row['level']} تغییر کرد: {status}"
        await _process_event(
            f"kyc:{row['id']}", status, int(row["user_id"]), message
        )


async def notification_watcher() -> None:
    while True:
        try:
            await scan_user_notifications()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("User notification watcher scan failed")
        await asyncio.sleep(5)

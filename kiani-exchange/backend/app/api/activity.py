import html
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..admin_notify import now_text, send_admin_message
from ..auth import get_current_user_id
from ..database import get_db

router = APIRouter()


class UserActivityRequest(BaseModel):
    action: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=240)
    path: str | None = Field(default=None, max_length=240)


@router.post("/user/activity")
async def report_user_activity(
    req: UserActivityRequest,
    user_id: int = Depends(get_current_user_id),
):
    with get_db() as conn:
        user = conn.execute(
            "SELECT first_name, last_name, phone_number, verification_level FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            return {"status": "ignored"}

        details = {
            "user_id": user_id,
            "action": req.action,
            "label": req.label,
            "path": req.path,
        }
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            ("user_activity", json.dumps(details, ensure_ascii=False)),
        )

    action = html.escape(req.action)
    label = html.escape(req.label or "-")
    path = html.escape(req.path or "-")
    name = html.escape(f"{user['first_name']} {user['last_name']}")
    phone = html.escape(user["phone_number"] or "-")

    await send_admin_message(
        "👆 <b>فعالیت کاربر</b>\n"
        f"👤 {name}\n"
        f"📱 {phone}\n"
        f"✅ سطح احراز: {int(user['verification_level'] or 1)}\n"
        f"🔹 رویداد: {action}\n"
        f"📝 بخش/دکمه: {label}\n"
        f"🌐 مسیر: {path}\n"
        f"⏰ زمان: {now_text()}"
    )
    return {"status": "ok"}

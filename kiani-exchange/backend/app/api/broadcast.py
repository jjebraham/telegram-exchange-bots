from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from ..database import get_db
from ..auth import verify_admin_token

router = APIRouter()


class BroadcastCreate(BaseModel):
    message: str
    target: str = "all"  # "all", "verified", "pending"


@router.post("/admin/broadcast")
async def create_broadcast(data: BroadcastCreate, _admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        # Count target users
        if data.target == "verified":
            count = db.execute("SELECT COUNT(*) as c FROM users WHERE kyc_status = 'Approved'").fetchone()["c"]
        elif data.target == "pending":
            count = db.execute("SELECT COUNT(*) as c FROM users WHERE kyc_status = 'Pending'").fetchone()["c"]
        else:
            count = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]

        cursor = db.execute(
            "INSERT INTO broadcasts (message, target, sent_count, status) VALUES (?, ?, ?, 'sent')",
            (data.message, data.target, count)
        )
        db.commit()

        db.execute(
            "INSERT INTO admin_logs (admin_user, action, details) VALUES (?, ?, ?)",
            (_admin.get("username", "admin"), "broadcast", f"Broadcast to {data.target}: {count} users")
        )
        db.commit()

        return {
            "status": "success",
            "broadcast_id": cursor.lastrowid,
            "target_count": count,
        }
    finally:
        db.close()


@router.get("/admin/broadcasts")
async def get_broadcasts(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    _admin: dict = Depends(verify_admin_token)
):
    db = get_db()
    try:
        offset = (page - 1) * limit
        total = db.execute("SELECT COUNT(*) as count FROM broadcasts").fetchone()["count"]
        rows = db.execute(
            "SELECT * FROM broadcasts ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        return {
            "broadcasts": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit if total > 0 else 1,
        }
    finally:
        db.close()


@router.get("/admin/broadcast/{broadcast_id}/status")
async def get_broadcast_status(broadcast_id: int, _admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM broadcasts WHERE id = ?", (broadcast_id,)).fetchone()
        if not row:
            return {"error": "Broadcast not found"}
        return dict(row)
    finally:
        db.close()

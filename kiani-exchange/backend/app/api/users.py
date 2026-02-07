from fastapi import APIRouter, Depends, Query
from ..database import get_db
from ..auth import verify_admin_token, verify_token

router = APIRouter()


@router.get("/users")
async def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str = Query("", description="Search by name, phone, or reference code"),
    kyc_status: str = Query("", description="Filter by KYC status"),
    _admin: dict = Depends(verify_admin_token)
):
    db = get_db()
    try:
        offset = (page - 1) * limit
        params = []
        where_clauses = []

        if search:
            where_clauses.append(
                "(first_name LIKE ? OR last_name LIKE ? OR phone_number LIKE ? OR reference_code LIKE ?)"
            )
            params.extend([f"%{search}%"] * 4)

        if kyc_status:
            where_clauses.append("kyc_status = ?")
            params.append(kyc_status)

        where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        total = db.execute(f"SELECT COUNT(*) as count FROM users{where_sql}", params).fetchone()["count"]
        rows = db.execute(
            f"SELECT id, first_name, last_name, phone_number, kyc_status, reference_code, "
            f"created_at, suspended FROM users{where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()

        return {
            "users": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit if total > 0 else 1,
        }
    finally:
        db.close()


@router.get("/users/{user_id}")
async def get_user(user_id: int, _admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return {"error": "User not found"}
        cards = db.execute("SELECT card_number FROM bank_cards WHERE user_id = ?", (user_id,)).fetchall()
        user_dict = dict(user)
        user_dict["extra_cards"] = [c["card_number"] for c in cards]
        return user_dict
    finally:
        db.close()


@router.post("/users/{user_id}/suspend")
async def suspend_user(user_id: int, _admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        db.execute("UPDATE users SET suspended = 1 WHERE id = ?", (user_id,))
        db.commit()
        return {"status": "success", "message": "User suspended"}
    finally:
        db.close()


@router.post("/users/{user_id}/activate")
async def activate_user(user_id: int, _admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        db.execute("UPDATE users SET suspended = 0 WHERE id = ?", (user_id,))
        db.commit()
        return {"status": "success", "message": "User activated"}
    finally:
        db.close()


@router.get("/me")
async def get_me(token_data: dict = Depends(verify_token)):
    db = get_db()
    try:
        user = db.execute("SELECT * FROM users WHERE id = ?", (int(token_data["sub"]),)).fetchone()
        if not user:
            return {"error": "User not found"}
        return dict(user)
    finally:
        db.close()

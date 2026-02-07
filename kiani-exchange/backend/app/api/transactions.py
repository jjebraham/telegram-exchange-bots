import random
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from ..database import get_db
from ..auth import verify_token, verify_admin_token

router = APIRouter()


class TransactionCreate(BaseModel):
    type: str
    from_currency: str
    to_currency: str
    amount: float
    rate: float
    total: float
    fee: float = 0


@router.post("/transactions")
async def create_transaction(data: TransactionCreate, token_data: dict = Depends(verify_token)):
    user_id = int(token_data["sub"])
    db = get_db()
    try:
        ref = f"TXN-{random.randint(100000, 999999)}"
        db.execute(
            "INSERT INTO transactions (user_id, type, from_currency, to_currency, amount, rate, total, fee, reference_code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, data.type, data.from_currency, data.to_currency, data.amount, data.rate, data.total, data.fee, ref)
        )
        db.commit()
        return {"status": "success", "reference_code": ref}
    finally:
        db.close()


@router.get("/transactions")
async def get_user_transactions(token_data: dict = Depends(verify_token)):
    user_id = int(token_data["sub"])
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        return {"transactions": [dict(r) for r in rows]}
    finally:
        db.close()


@router.get("/admin/transactions")
async def get_all_transactions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str = Query(""),
    _admin: dict = Depends(verify_admin_token)
):
    db = get_db()
    try:
        offset = (page - 1) * limit
        params = []
        where = ""

        if status:
            where = " WHERE t.status = ?"
            params.append(status)

        total = db.execute(
            f"SELECT COUNT(*) as count FROM transactions t{where}", params
        ).fetchone()["count"]

        rows = db.execute(
            f"SELECT t.*, u.first_name, u.last_name FROM transactions t "
            f"LEFT JOIN users u ON t.user_id = u.id{where} "
            f"ORDER BY t.created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()

        return {
            "transactions": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit if total > 0 else 1,
        }
    finally:
        db.close()

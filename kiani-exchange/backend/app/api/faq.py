from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..auth import verify_admin_token

router = APIRouter()


class FAQCreate(BaseModel):
    question_fa: str
    answer_fa: str
    question_en: str = ""
    answer_en: str = ""
    category: str = "general"
    sort_order: int = 0


class FAQUpdate(BaseModel):
    question_fa: Optional[str] = None
    answer_fa: Optional[str] = None
    question_en: Optional[str] = None
    answer_en: Optional[str] = None
    category: Optional[str] = None
    sort_order: Optional[int] = None


@router.get("/faqs")
async def get_faqs():
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM faqs ORDER BY sort_order ASC, id ASC").fetchall()
        return {"faqs": [dict(r) for r in rows]}
    finally:
        db.close()


@router.get("/faqs/{faq_id}")
async def get_faq(faq_id: int):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM faqs WHERE id = ?", (faq_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="FAQ not found")
        return dict(row)
    finally:
        db.close()


@router.post("/admin/faq")
async def create_faq(data: FAQCreate, _admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO faqs (question_fa, answer_fa, question_en, answer_en, category, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (data.question_fa, data.answer_fa, data.question_en, data.answer_en, data.category, data.sort_order)
        )
        db.commit()
        return {"status": "success", "id": cursor.lastrowid}
    finally:
        db.close()


@router.put("/admin/faq/{faq_id}")
async def update_faq(faq_id: int, data: FAQUpdate, _admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        existing = db.execute("SELECT * FROM faqs WHERE id = ?", (faq_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="FAQ not found")

        updates = {}
        for field in ["question_fa", "answer_fa", "question_en", "answer_en", "category", "sort_order"]:
            val = getattr(data, field)
            if val is not None:
                updates[field] = val

        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [faq_id]
            db.execute(f"UPDATE faqs SET {set_clause} WHERE id = ?", values)
            db.commit()

        return {"status": "success"}
    finally:
        db.close()


@router.delete("/admin/faq/{faq_id}")
async def delete_faq(faq_id: int, _admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        db.execute("DELETE FROM faqs WHERE id = ?", (faq_id,))
        db.commit()
        return {"status": "success"}
    finally:
        db.close()

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from ..database import get_db
from ..auth import verify_token, verify_admin_token

router = APIRouter()

# Simple FAQ-based chatbot responses
FAQ_RESPONSES = {
    "ثبت نام": "روی دکمه ثبت نام بزنید و با وارد کردن نام، نام خانوادگی، کد ملی، تاریخ تولد، شماره تلگرام ایرانی و شماره کارت بانکی به نام خودتان ثبت نام کنید.",
    "شماره تلفن": "تنها شماره تلفن ایران مورد قبول است و فقط با به اشتراک گذاری شماره تلفن تلگرام تان می‌توانید ثبت نام را تکمیل کنید.",
    "کارت": "پس از ورود به حساب کاربری، از منوی 'کارت های بانکی من' روی گزینه 'اضافه کردن کارت جدید' بزنید.",
    "واریز ریالی": "واریز های ریالی در اولین سیکل پایا به حساب بانکی شما واریز می‌شود. سیکل‌ها: 04:00، 11:00، 14:00، 19:00",
    "تتر": "اگر اولین واریز ریالی شما باشد، مبلغ 72 ساعت نزد ما باقی می‌ماند. از خرید دوم ظرف یک ساعت تراکنش انجام می‌شود.",
    "حساب شخص دیگر": "خیر، شما تنها از حساب بانکی به نام خودتان می‌توانید واریز ریالی داشته باشید.",
    "احراز هویت": "احراز هویت شامل تطابق کارت بانکی با کد ملی و آپلود تصویر کارت ملی است.",
    "پشتیبانی": "برای تماس با پشتیبانی: @TL905411603664 یا تماس با شماره +90 212 294 33 34",
}


class ChatQuestion(BaseModel):
    question: str


class FeedbackRequest(BaseModel):
    log_id: int
    helpful: bool


def find_best_answer(question: str) -> tuple[str, float]:
    question_lower = question.lower().strip()

    # Check FAQ database first
    db = get_db()
    try:
        faqs = db.execute("SELECT question_fa, answer_fa FROM faqs ORDER BY sort_order ASC").fetchall()
        for faq in faqs:
            q = faq["question_fa"].lower()
            if any(word in question_lower for word in q.split() if len(word) > 2):
                return faq["answer_fa"], 0.8
    finally:
        db.close()

    # Check hardcoded responses
    best_answer = None
    best_score = 0
    for keyword, answer in FAQ_RESPONSES.items():
        if keyword in question_lower:
            score = len(keyword) / len(question_lower) if question_lower else 0
            if score > best_score:
                best_score = score
                best_answer = answer

    if best_answer:
        return best_answer, min(best_score + 0.3, 1.0)

    return "متاسفانه پاسخ سوال شما را نمی‌دانم. لطفا با پشتیبانی تماس بگیرید: @TL905411603664", 0.1


@router.post("/chatbot/ask")
async def ask_chatbot(data: ChatQuestion, token_data: dict = Depends(verify_token)):
    user_id = int(token_data["sub"])
    answer, confidence = find_best_answer(data.question)

    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO chatbot_logs (user_id, question, answer, confidence) VALUES (?, ?, ?, ?)",
            (user_id, data.question, answer, confidence)
        )
        db.commit()
        log_id = cursor.lastrowid
    finally:
        db.close()

    return {"answer": answer, "confidence": confidence, "log_id": log_id}


@router.post("/chatbot/feedback")
async def chatbot_feedback(data: FeedbackRequest, token_data: dict = Depends(verify_token)):
    db = get_db()
    try:
        db.execute("UPDATE chatbot_logs SET helpful = ? WHERE id = ?", (1 if data.helpful else 0, data.log_id))
        db.commit()
        return {"status": "success"}
    finally:
        db.close()


@router.get("/admin/chatbot/logs")
async def get_chatbot_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user_id: int = Query(None),
    _admin: dict = Depends(verify_admin_token)
):
    db = get_db()
    try:
        offset = (page - 1) * limit
        params = []
        where = ""

        if user_id:
            where = " WHERE cl.user_id = ?"
            params.append(user_id)

        total = db.execute(
            f"SELECT COUNT(*) as count FROM chatbot_logs cl{where}", params
        ).fetchone()["count"]

        rows = db.execute(
            f"SELECT cl.*, u.first_name, u.last_name FROM chatbot_logs cl "
            f"LEFT JOIN users u ON cl.user_id = u.id{where} "
            f"ORDER BY cl.created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()

        return {
            "logs": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit if total > 0 else 1,
        }
    finally:
        db.close()

from fastapi import APIRouter, Depends, UploadFile, File
from pydantic import BaseModel
from ..database import get_db
from ..auth import verify_admin_token, verify_token
from typing import Optional

router = APIRouter()


class KYCSubmission(BaseModel):
    national_id: str
    dob: str
    bank_card_number: str


class KYCRejectRequest(BaseModel):
    reason: str = ""


@router.get("/kyc/pending")
async def get_pending_kyc(_admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, first_name, last_name, phone_number, national_id, dob, "
            "bank_card_number, front_id, back_id, reference_code, created_at "
            "FROM users WHERE kyc_status = 'Pending' AND national_id IS NOT NULL "
            "ORDER BY created_at DESC"
        ).fetchall()
        return {"pending": [dict(r) for r in rows]}
    finally:
        db.close()


@router.get("/kyc/approved")
async def get_approved_kyc(_admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, first_name, last_name, phone_number, kyc_status, reference_code, created_at "
            "FROM users WHERE kyc_status = 'Approved' ORDER BY created_at DESC"
        ).fetchall()
        return {"approved": [dict(r) for r in rows]}
    finally:
        db.close()


@router.get("/kyc/rejected")
async def get_rejected_kyc(_admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, first_name, last_name, phone_number, kyc_status, reference_code, created_at "
            "FROM users WHERE kyc_status = 'Rejected' ORDER BY created_at DESC"
        ).fetchall()
        return {"rejected": [dict(r) for r in rows]}
    finally:
        db.close()


@router.post("/kyc/{user_id}/approve")
async def approve_kyc(user_id: int, _admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        db.execute("UPDATE users SET kyc_status = 'Approved', kyc_notified = 0 WHERE id = ?", (user_id,))
        db.commit()

        db.execute(
            "INSERT INTO admin_logs (admin_user, action, details) VALUES (?, ?, ?)",
            (_admin.get("username", "admin"), "kyc_approve", f"Approved KYC for user {user_id}")
        )
        db.commit()

        return {"status": "success", "message": f"KYC approved for user {user_id}"}
    finally:
        db.close()


@router.post("/kyc/{user_id}/reject")
async def reject_kyc(user_id: int, req: KYCRejectRequest, _admin: dict = Depends(verify_admin_token)):
    db = get_db()
    try:
        db.execute("UPDATE users SET kyc_status = 'Rejected', kyc_notified = 0 WHERE id = ?", (user_id,))
        db.commit()

        db.execute(
            "INSERT INTO admin_logs (admin_user, action, details) VALUES (?, ?, ?)",
            (_admin.get("username", "admin"), "kyc_reject", f"Rejected KYC for user {user_id}: {req.reason}")
        )
        db.commit()

        return {"status": "success", "message": f"KYC rejected for user {user_id}"}
    finally:
        db.close()


@router.post("/kyc/submit")
async def submit_kyc(data: KYCSubmission, token_data: dict = Depends(verify_token)):
    user_id = int(token_data["sub"])
    db = get_db()
    try:
        db.execute(
            "UPDATE users SET national_id = ?, dob = ?, bank_card_number = ?, kyc_status = 'Pending' WHERE id = ?",
            (data.national_id, data.dob, data.bank_card_number, user_id)
        )
        db.commit()
        return {"status": "success", "message": "KYC submitted successfully"}
    finally:
        db.close()


@router.get("/kyc/status")
async def get_kyc_status(token_data: dict = Depends(verify_token)):
    user_id = int(token_data["sub"])
    db = get_db()
    try:
        row = db.execute("SELECT kyc_status FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return {"status": "not_found"}
        return {"kyc_status": row["kyc_status"]}
    finally:
        db.close()

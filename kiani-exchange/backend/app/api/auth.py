from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..database import get_db
from ..auth import create_token
from ..config import ADMIN_USERNAME, ADMIN_PASSWORD

router = APIRouter()


class TelegramAuthRequest(BaseModel):
    telegram_id: int
    first_name: str = ""
    last_name: str = ""


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    telegram_id: int
    first_name: str
    last_name: str
    phone_number: str


@router.post("/auth/telegram")
async def telegram_auth(req: TelegramAuthRequest):
    db = get_db()
    try:
        user = db.execute("SELECT * FROM users WHERE id = ?", (req.telegram_id,)).fetchone()
        if user:
            token = create_token({"sub": str(user["id"]), "name": f"{user['first_name']} {user['last_name']}"})
            return {
                "status": "success",
                "token": token,
                "user": {
                    "id": user["id"],
                    "first_name": user["first_name"],
                    "last_name": user["last_name"],
                    "phone_number": user["phone_number"],
                    "kyc_status": user["kyc_status"],
                    "reference_code": user["reference_code"],
                }
            }
        return {"status": "not_registered", "message": "User not found. Please register."}
    finally:
        db.close()


@router.post("/auth/register")
async def register_user(req: RegisterRequest):
    db = get_db()
    try:
        existing = db.execute("SELECT id FROM users WHERE id = ? OR phone_number = ?",
                              (req.telegram_id, req.phone_number)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="User already exists")

        import random
        ref_code = str(random.randint(1000, 9999))
        db.execute(
            "INSERT INTO users (id, first_name, last_name, phone_number, reference_code) VALUES (?, ?, ?, ?, ?)",
            (req.telegram_id, req.first_name, req.last_name, req.phone_number, ref_code)
        )
        db.commit()

        token = create_token({"sub": str(req.telegram_id), "name": f"{req.first_name} {req.last_name}"})
        return {
            "status": "success",
            "token": token,
            "user": {
                "id": req.telegram_id,
                "first_name": req.first_name,
                "last_name": req.last_name,
                "phone_number": req.phone_number,
                "kyc_status": "Pending",
                "reference_code": ref_code,
            }
        }
    finally:
        db.close()


@router.post("/admin/login")
async def admin_login(req: AdminLoginRequest):
    if req.username == ADMIN_USERNAME and req.password == ADMIN_PASSWORD:
        token = create_token({"sub": "admin", "username": req.username}, is_admin=True)
        return {"status": "success", "token": token, "username": req.username}
    raise HTTPException(status_code=401, detail="Invalid credentials")

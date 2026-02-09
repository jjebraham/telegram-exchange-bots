import aiohttp
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from ..database import get_db
from ..auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user_id,
)

EHRAZ_TOKEN = "5942b9d62abc20405dadfb2c0f546b669cf1471c"
PROXY_URL = "http://jjebraham-25:Amir1234@p.webshare.io:80"

router = APIRouter()


class RegisterRequest(BaseModel):
    first_name: str
    last_name: str
    national_id: str
    date_of_birth: str
    bank_card_number: str
    phone_number: str
    password: str


class LoginRequest(BaseModel):
    phone_number: str
    password: str


class EhrazRequest(BaseModel):
    cardNumber: str
    nationalCode: str
    birthDate: str


def _user_dict(row):
    return {
        "id": row["id"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "phone_number": row["phone_number"],
        "kyc_status": row["kyc_status"],
        "verification_level": row["verification_level"]
        if "verification_level" in row.keys()
        else 1,
    }


@router.post("/users/register")
async def register_user(req: RegisterRequest):
    hashed = hash_password(req.password)

    with get_db() as conn:
        # Check if phone number already exists
        existing = conn.execute(
            "SELECT id FROM users WHERE phone_number = ?",
            (req.phone_number,),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="این شماره موبایل قبلاً ثبت شده است",
            )

        conn.execute(
            """INSERT INTO users
               (first_name, last_name, national_id, dob,
                bank_card_number, phone_number, password_hash,
                accepted_terms, kyc_status, verification_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'Pending', 1)""",
            (
                req.first_name,
                req.last_name,
                req.national_id,
                req.date_of_birth,
                req.bank_card_number,
                req.phone_number,
                hashed,
            ),
        )
        conn.commit()

    return {"status": "success", "message": "User registered"}


@router.post("/users/login")
async def login_user(req: LoginRequest):
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE phone_number = ?",
            (req.phone_number,),
        ).fetchone()

    if not user or not user["password_hash"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"user_id": user["id"]})

    return {"token": token, "user": _user_dict(user)}


@router.get("/users/me")
async def get_me(user_id: int = Depends(get_current_user_id)):
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"user": _user_dict(user)}


@router.post("/verify/ehraz")
async def verify_with_ehraz(req: EhrazRequest):
    url = "https://ehraz.io/api/v1/match/card-with-national"
    headers = {
        "Authorization": f"Token {EHRAZ_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={
                    "cardNumber": req.cardNumber,
                    "nationalCode": req.nationalCode,
                    "birthDate": req.birthDate,
                },
                headers=headers,
                proxy=PROXY_URL,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                return {"matched": data.get("matched", False)}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Verification service unavailable",
        )

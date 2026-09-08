from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import admin, kyc, users
from app.auth import create_access_token
from app.database import get_db


def _user_app() -> TestClient:
    app = FastAPI()
    app.include_router(users.router, prefix="/api")
    app.include_router(kyc.router, prefix="/api")
    return TestClient(app)


def _admin_app() -> TestClient:
    app = FastAPI()
    app.include_router(admin.router, prefix="/api")
    return TestClient(app)


def test_registration_preserves_multiword_persian_names_and_starts_level1(isolated_db, monkeypatch):
    async def fake_verify(_req):
        return None

    async def fake_notify(_message):
        return True

    monkeypatch.setattr(users, "_verify_registration_with_ehraz", fake_verify)
    monkeypatch.setattr(users, "send_admin_message", fake_notify)

    client = _user_app()
    response = client.post(
        "/api/users/register",
        json={
            "first_name": "محمد رضا",
            "last_name": "کریمی برجویی اصل مشهدی",
            "national_id": "1234567890",
            "date_of_birth": "13700101",
            "bank_card_number": "6037991234567890",
            "phone_number": "09121111111",
            "password": "UserPassword123",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["verification_level"] == 1

    with get_db() as conn:
        row = conn.execute(
            "SELECT first_name, last_name, kyc_status, verification_level FROM users WHERE phone_number = ?",
            ("09121111111",),
        ).fetchone()
    assert row["first_name"] == "محمد رضا"
    assert row["last_name"] == "کریمی برجویی اصل مشهدی"
    assert row["kyc_status"] == "Approved"
    assert row["verification_level"] == 1


def test_level2_upload_stays_pending_until_admin_approval(isolated_db, tmp_path, monkeypatch):
    async def fake_kyc_notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(kyc, "UPLOAD_ROOT", (tmp_path / "kyc_uploads").resolve())
    monkeypatch.setattr(kyc, "_notify_admin_submission", fake_kyc_notify)

    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO users
               (first_name, last_name, phone_number, national_id, dob,
                bank_card_number, accepted_terms, kyc_status, password_hash, verification_level)
               VALUES ('علی', 'احمدی', '09122222222', '2345678901', '13690101',
                       '6037999876543210', 1, 'Approved', 'unused', 1)"""
        )
        user_id = int(cursor.lastrowid)

    user_token = create_access_token({"user_id": user_id})
    user_client = _user_app()

    # Real PNG signature: the KYC API validates file contents,
    # not merely the browser-provided MIME type.
    png_signature = bytes.fromhex("89504e470d0a1a0a")

    response = user_client.post(
        "/api/kyc/level2",
        headers={"Authorization": f"Bearer {user_token}"},
        files={
            "front": (
                "front.png",
                png_signature + b"front-image-content",
                "image/png",
            ),
            "back": (
                "back.png",
                png_signature + b"back-image-content",
                "image/png",
            ),
        },
    )
    assert response.status_code == 200, response.text
    submission_id = response.json()["submission_id"]

    with get_db() as conn:
        user = conn.execute("SELECT verification_level FROM users WHERE id = ?", (user_id,)).fetchone()
        submission = conn.execute("SELECT status FROM kyc_submissions WHERE id = ?", (submission_id,)).fetchone()
    assert user["verification_level"] == 1
    assert submission["status"] == "pending"

    admin_client = _admin_app()
    login = admin_client.post(
        "/api/admin/login",
        json={"username": "admin-test", "password": "AdminTestPassword123"},
    )
    assert login.status_code == 200
    admin_token = login.json()["token"]

    unauthorized_file = admin_client.get(
        f"/api/admin/kyc/submissions/{submission_id}/file/front"
    )
    assert unauthorized_file.status_code == 403

    file_response = admin_client.get(
        f"/api/admin/kyc/submissions/{submission_id}/file/front",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert file_response.status_code == 200
    assert file_response.content == png_signature + b"front-image-content"
    assert "no-store" in file_response.headers.get("cache-control", "")

    approve = admin_client.post(
        f"/api/admin/kyc/submissions/{submission_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["verification_level"] == 2

    with get_db() as conn:
        user = conn.execute("SELECT verification_level FROM users WHERE id = ?", (user_id,)).fetchone()
        submission = conn.execute("SELECT status FROM kyc_submissions WHERE id = ?", (submission_id,)).fetchone()
    assert user["verification_level"] == 2
    assert submission["status"] == "approved"

    assert Path(kyc.UPLOAD_ROOT / str(user_id)).is_dir()



def test_kyc_supported_file_signatures():
    samples = {
        "jpeg": (
            bytes.fromhex("ffd8ffe0") + b"jpeg-content",
            ("image/jpeg", ".jpg"),
        ),
        "png": (
            bytes.fromhex("89504e470d0a1a0a") + b"png-content",
            ("image/png", ".png"),
        ),
        "webp": (
            b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"webp-content",
            ("image/webp", ".webp"),
        ),
        "pdf": (
            b"%PDF-1.7\n" + b"pdf-content",
            ("application/pdf", ".pdf"),
        ),
        "heic": (
            b"\x00\x00\x00\x18ftypheic" + b"heic-content",
            ("image/heic", ".heic"),
        ),
        "heif": (
            b"\x00\x00\x00\x18ftypmif1" + b"heif-content",
            ("image/heif", ".heif"),
        ),
    }

    for _name, (content, expected) in samples.items():
        assert kyc._detect_upload_format(content) == expected

    # MIME/extension spoofing must not be enough to pass validation.
    assert kyc._detect_upload_format(
        b"this is not really an image"
    ) is None

    # SVG is intentionally not accepted because it can contain active content.
    assert kyc._detect_upload_format(
        b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    ) is None

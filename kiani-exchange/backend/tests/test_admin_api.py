from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import admin
from app.auth import hash_password
from app.database import get_db


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin.router, prefix="/api")
    return TestClient(app)


def _seed_user():
    with get_db() as conn:
        conn.execute(
            """INSERT INTO users
               (first_name, last_name, phone_number, national_id, dob,
                bank_card_number, accepted_terms, kyc_status, password_hash, verification_level)
               VALUES (?, ?, ?, ?, ?, ?, 1, 'Approved', ?, 1)""",
            (
                "محمد رضا",
                "کریمی برجویی اصل مشهدی",
                "09121111111",
                "1234567890",
                "13700101",
                "6037991234567890",
                hash_password("UserPassword123"),
            ),
        )


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/admin/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "password" not in data
    assert data["token_type"] == "bearer"
    return data["token"]


def test_admin_endpoints_require_bearer_token(isolated_db):
    _seed_user()
    client = _client()

    response = client.get(
        "/api/admin/users",
        params={"username": "admin-test", "password": "AdminTestPassword123"},
    )
    assert response.status_code == 403

    token = _login(client, "admin-test", "AdminTestPassword123")
    response = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    user = response.json()["users"][0]
    assert user["national_id"] == "***7890"
    assert user["bank_card_number"] == "**** **** **** 7890"


def test_sensitive_user_detail_is_audited_and_role_limited(isolated_db):
    _seed_user()
    client = _client()

    admin_token = _login(client, "admin-test", "AdminTestPassword123")
    detail = client.get(
        "/api/admin/users/1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["user"]["national_id"] == "1234567890"

    with get_db() as conn:
        row = conn.execute(
            "SELECT action FROM admin_logs WHERE action = 'view_user_sensitive_details' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None

    viewer_token = _login(client, "viewer-test", "ViewerTestPassword123")
    denied = client.get(
        "/api/admin/users/1",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert denied.status_code == 403

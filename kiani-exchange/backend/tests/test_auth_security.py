import os

import pytest
from fastapi import HTTPException

from app import auth
from app.admin_auth import (
    create_admin_access_token,
    decode_admin_token,
    verify_admin_credentials,
)


def test_user_token_round_trip():
    token = auth.create_access_token({"user_id": 42})
    payload = auth.decode_token(token)
    assert payload["user_id"] == 42
    assert payload["token_type"] == "user"


def test_admin_login_creates_admin_only_token():
    identity = verify_admin_credentials("admin-test", "AdminTestPassword123")
    assert identity is not None
    token, expires_in = create_admin_access_token(identity)
    decoded = decode_admin_token(token)
    assert decoded.username == "admin-test"
    assert decoded.role == "admin"
    assert expires_in == 30 * 60

    with pytest.raises(HTTPException):
        auth.decode_token(token)


def test_user_token_cannot_be_used_as_admin():
    token = auth.create_access_token({"user_id": 7})
    with pytest.raises(HTTPException):
        decode_admin_token(token)


def test_auth_config_rejects_short_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "short")
    with pytest.raises(RuntimeError):
        auth.validate_auth_config()


def test_no_default_admin_password_when_env_missing(monkeypatch):
    monkeypatch.delenv("ADMIN_PANEL_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PANEL_PASSWORD", raising=False)
    assert verify_admin_credentials("admin", "admin123") is None

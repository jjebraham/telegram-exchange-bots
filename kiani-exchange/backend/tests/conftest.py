import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Test-only credentials. Never use these values in production.
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-that-is-longer-than-thirty-two-characters")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_HOURS", "4")
os.environ.setdefault("ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("ADMIN_PANEL_USERNAME", "admin-test")
os.environ.setdefault("ADMIN_PANEL_PASSWORD", "AdminTestPassword123")
os.environ.setdefault("SUPPORT_PANEL_USERNAME", "support-test")
os.environ.setdefault("SUPPORT_PANEL_PASSWORD", "SupportTestPassword123")
os.environ.setdefault("VIEWER_PANEL_USERNAME", "viewer-test")
os.environ.setdefault("VIEWER_PANEL_PASSWORD", "ViewerTestPassword123")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "https://miniapp.peerexo.com,https://kianiapp.peerexo.com")
os.environ.setdefault("TELEGRAM_ADMIN_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_ADMIN_CHAT_ID", "0")
os.environ.setdefault("TELEGRAM_USER_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("EHRAZ_TOKEN", "test-ehraz-token")
os.environ.setdefault("KYC_TEST_MODE", "false")
os.environ.setdefault("ALLOW_KYC_TEST_MODE", "false")

from app import database


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "users-test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()
    return db_path

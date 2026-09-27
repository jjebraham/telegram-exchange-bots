import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.admin_auth import (
    create_admin_session_token,
    decode_admin_session_token,
)


class AdminAuthTests(unittest.TestCase):
    def test_admin_session_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / "admin.secret"
            secret.write_text("x" * 64, encoding="utf-8")
            with patch.dict(
                os.environ,
                {"KIANI_ADMIN_SESSION_SECRET_FILE": str(secret)},
                clear=False,
            ):
                token = create_admin_session_token("admin", "admin")
                payload = decode_admin_session_token(token)

        self.assertEqual(payload["username"], "admin")
        self.assertEqual(payload["role"], "admin")

    def test_missing_secret_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.secret"
            with patch.dict(
                os.environ,
                {
                    "KIANI_ADMIN_SESSION_SECRET": "",
                    "KIANI_ADMIN_SESSION_SECRET_FILE": str(missing),
                },
                clear=False,
            ):
                with self.assertRaises(RuntimeError):
                    create_admin_session_token("admin", "admin")


if __name__ == "__main__":
    unittest.main()

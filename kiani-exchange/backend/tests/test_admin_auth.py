"""Test the production credential resolver without starting the API or database."""

import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch


def load_admin_role():
    # The API module initializes external services on import; isolate its pure
    # resolver while executing the actual source, including configured defaults.
    source = Path(__file__).parents[1] / "app" / "api" / "users.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    resolver = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_admin_role")
    namespace = {"os": os}
    exec(compile(ast.Module(body=[resolver], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["_admin_role"]


class AdminAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.resolve = load_admin_role()
        self.credentials = {
            "ADMIN_PANEL_USERNAME": "test-admin",
            "ADMIN_PANEL_PASSWORD": "test-admin-password",
            "SUPPORT_PANEL_USERNAME": "test-support",
            "SUPPORT_PANEL_PASSWORD": "test-support-password",
            "VIEWER_PANEL_USERNAME": "test-viewer",
            "VIEWER_PANEL_PASSWORD": "test-viewer-password",
        }

    def test_unconfigured_optional_accounts_cannot_log_in_with_empty_fields(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(self.resolve("", ""))
        with patch.dict(os.environ, {
            "SUPPORT_PANEL_USERNAME": "", "SUPPORT_PANEL_PASSWORD": "",
            "VIEWER_PANEL_USERNAME": "", "VIEWER_PANEL_PASSWORD": "",
        }, clear=True):
            self.assertIsNone(self.resolve("", ""))

    def test_partially_configured_accounts_cannot_log_in(self):
        for username, password in (("test-support", ""), ("", "password")):
            with self.subTest(username=username), patch.dict(os.environ, {
                "SUPPORT_PANEL_USERNAME": username,
                "SUPPORT_PANEL_PASSWORD": password,
            }, clear=True):
                self.assertIsNone(self.resolve(username, password))

    def test_valid_configured_roles_still_log_in(self):
        with patch.dict(os.environ, self.credentials, clear=True):
            for role in ("admin", "support", "viewer"):
                with self.subTest(role=role):
                    self.assertEqual(self.resolve(f"test-{role}", f"test-{role}-password"), role)

    def test_wrong_credentials_are_rejected(self):
        with patch.dict(os.environ, self.credentials, clear=True):
            self.assertIsNone(self.resolve("test-admin", "wrong-password"))
            self.assertIsNone(self.resolve("unknown", "test-admin-password"))


if __name__ == "__main__":
    unittest.main()

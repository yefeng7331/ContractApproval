"""API evidence for local identities and revocable role-bound sessions."""

import unittest
from datetime import datetime, timedelta, timezone
from contextlib import redirect_stdout
from io import StringIO
from typing import Annotated
from unittest.mock import patch

from fastapi import Depends
from fastapi.testclient import TestClient

from backend.auth import AuthStore, User
from backend.cli import main as create_user_cli
from backend.main import create_app, require_roles


class AuthApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.now = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)
        cls.store = AuthStore(":memory:", clock=lambda: cls.now)
        cls.store.initialize()
        for username, role in (("business1", "business"), ("legal1", "legal"), ("admin1", "admin")):
            cls.store.create_user(username, role, "sample-test-password")
        cls.app = create_app(auth_store=cls.store)

        @cls.app.get("/test/legal-only")
        def legal_only(user: Annotated[User, Depends(require_roles("legal"))]):
            return {"username": user.username}

        cls.client = TestClient(cls.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        cls.store.close()

    def _login(self, username: str, password: str = "sample-test-password") -> dict:
        response = self.client.post(
            "/api/v1/sessions", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_three_roles_and_server_side_denial(self) -> None:
        for username, expected_role in (
            ("business1", "business"),
            ("legal1", "legal"),
            ("admin1", "admin"),
        ):
            with self.subTest(role=expected_role):
                login = self._login(username)
                self.assertEqual(login["user"], {"username": username, "role": expected_role})
                self.assertEqual(login["token_type"], "bearer")
                headers = self._headers(login["access_token"])
                current = self.client.get("/api/v1/sessions/current", headers=headers)
                self.assertEqual(current.status_code, 200)
                self.assertEqual(current.json()["role"], expected_role)
                protected = self.client.get("/test/legal-only", headers=headers)
                if expected_role == "legal":
                    self.assertEqual(protected.status_code, 200)
                else:
                    self.assertEqual(protected.status_code, 403)
                    self.assertEqual(protected.json()["code"], "FORBIDDEN")

    def test_missing_invalid_and_forged_role(self) -> None:
        missing = self.client.get("/api/v1/sessions/current")
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["code"], "AUTH_REQUIRED")
        invalid = self.client.get(
            "/api/v1/sessions/current", headers=self._headers("not-a-valid-token")
        )
        self.assertEqual(invalid.status_code, 401)
        forged = self.client.post(
            "/api/v1/sessions",
            json={"username": "business1", "password": "sample-test-password", "role": "legal"},
        )
        self.assertEqual(forged.status_code, 200)
        self.assertEqual(forged.json()["user"]["role"], "business")

    def test_bad_credentials_have_generic_error(self) -> None:
        errors = []
        for username, password in (
            ("business1", "wrong-password"),
            ("missing-user", "wrong-password"),
        ):
            response = self.client.post(
                "/api/v1/sessions", json={"username": username, "password": password}
            )
            self.assertEqual(response.status_code, 401)
            errors.append(response.json())
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(errors[0]["code"], "INVALID_CREDENTIALS")
        self.assertNotIn("wrong-password", str(errors[0]))

    def test_logout_revokes_session(self) -> None:
        token = self._login("business1")["access_token"]
        headers = self._headers(token)
        self.assertEqual(self.client.delete("/api/v1/sessions/current", headers=headers).status_code, 204)
        after = self.client.get("/api/v1/sessions/current", headers=headers)
        self.assertEqual(after.status_code, 401)
        self.assertEqual(after.json()["code"], "AUTH_INVALID")

    def test_session_expires(self) -> None:
        token = self._login("legal1")["access_token"]
        original = type(self).now
        try:
            type(self).now = original + timedelta(hours=9)
            response = self.client.get(
                "/api/v1/sessions/current", headers=self._headers(token)
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["code"], "AUTH_INVALID")
        finally:
            type(self).now = original

    def test_password_and_bearer_token_are_not_stored_verbatim(self) -> None:
        token = self._login("admin1")["access_token"]
        row = self.store._connection.execute(
            "SELECT password_hash, password_salt FROM users WHERE username = ?", ("admin1",)
        ).fetchone()
        self.assertNotEqual(bytes(row["password_hash"]), b"sample-test-password")
        self.assertEqual(len(bytes(row["password_salt"])), 16)
        session = self.store._connection.execute(
            "SELECT token_hash FROM sessions ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        self.assertNotEqual(session["token_hash"], token)
        self.assertEqual(len(session["token_hash"]), 64)

    def test_account_creation_cli_accepts_hidden_password_input(self) -> None:
        output = StringIO()
        arguments = [
            "backend.cli", "--database", ":memory:", "create-user",
            "--username", "operator1", "--role", "business",
        ]
        with patch("sys.argv", arguments), patch(
            "backend.cli.getpass.getpass", side_effect=["sample-test-password", "sample-test-password"]
        ), redirect_stdout(output):
            self.assertEqual(create_user_cli(), 0)
        self.assertIn("Created operator1 (business)", output.getvalue())
        self.assertNotIn("sample-test-password", output.getvalue())


if __name__ == "__main__":
    unittest.main()

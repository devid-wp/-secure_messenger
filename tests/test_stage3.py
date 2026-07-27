from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.test_foundation import run_migrations, sqlite_async_url


class DirectMessagesApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "stage3.db"
        run_migrations(self.database_path)
        settings = Settings(
            environment="test",
            database_url=sqlite_async_url(self.database_path),
        )
        self.client_context = TestClient(create_app(settings))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary_directory.cleanup()

    def register_and_login(self, login: str) -> str:
        registration = self.client.post(
            "/api/v1/auth/register",
            json={"login": login, "password": "password-123"},
        )
        self.assertEqual(registration.status_code, 201, registration.text)
        login_response = self.client.post(
            "/api/v1/auth/login",
            json={"login": login, "password": "password-123"},
        )
        self.assertEqual(login_response.status_code, 200, login_response.text)
        return login_response.json()["token"]

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_search_returns_only_matching_real_users(self) -> None:
        alice_token = self.register_and_login("alice")
        self.register_and_login("BobBuilder")
        self.register_and_login("bobby")
        self.register_and_login("charlie")

        response = self.client.get(
            "/api/v1/users/search",
            params={"q": "BoB"},
            headers=self.headers(alice_token),
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            [user["login"] for user in response.json()],
            ["BobBuilder", "bobby"],
        )

    def test_search_rejects_too_short_query(self) -> None:
        token = self.register_and_login("alice")
        response = self.client.get(
            "/api/v1/users/search",
            params={"q": "a"},
            headers=self.headers(token),
        )
        self.assertEqual(response.status_code, 422)

    def test_direct_chat_creation_is_idempotent_and_list_is_private(self) -> None:
        alice_token = self.register_and_login("alice")
        bob_token = self.register_and_login("bob")
        charlie_token = self.register_and_login("charlie")

        first = self.client.post(
            "/api/v1/chats/dm",
            json={"login": "bob"},
            headers=self.headers(alice_token),
        )
        second = self.client.post(
            "/api/v1/chats/dm",
            json={"login": "alice"},
            headers=self.headers(bob_token),
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])

        alice_chats = self.client.get(
            "/api/v1/chats/dm", headers=self.headers(alice_token)
        )
        charlie_chats = self.client.get(
            "/api/v1/chats/dm", headers=self.headers(charlie_token)
        )
        self.assertEqual([chat["id"] for chat in alice_chats.json()], [first.json()["id"]])
        self.assertEqual(charlie_chats.json(), [])


if __name__ == "__main__":
    unittest.main()

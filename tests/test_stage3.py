from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.test_foundation import run_migrations, sqlite_async_url


class DirectChatApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "direct-chat.db"
        run_migrations(self.database_path)
        settings = Settings(environment="test", database_url=sqlite_async_url(self.database_path))
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
        response = self.client.post(
            "/api/v1/auth/login",
            json={"login": login, "password": "password-123"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_search_returns_only_matching_real_users(self) -> None:
        alice = self.register_and_login("alice")
        self.register_and_login("BobBuilder")
        self.register_and_login("bobby")
        self.register_and_login("charlie")

        response = self.client.get(
            "/api/v1/users/search", params={"q": "BoB"}, headers=self.headers(alice)
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([user["login"] for user in response.json()], ["BobBuilder", "bobby"])

    def test_username_is_unique_and_keeps_stable_user_id(self) -> None:
        alice = self.register_and_login("alice")
        bob = self.register_and_login("bob")
        before = self.client.get("/api/v1/users/me", headers=self.headers(alice))
        changed = self.client.patch(
            "/api/v1/users/me", json={"username": "night_signal"}, headers=self.headers(alice)
        )
        duplicate = self.client.patch(
            "/api/v1/users/me", json={"username": "night_signal"}, headers=self.headers(bob)
        )

        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["id"], before.json()["id"])
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

    def test_direct_chat_is_idempotent_and_private(self) -> None:
        alice = self.register_and_login("alice")
        bob = self.register_and_login("bob")
        charlie = self.register_and_login("charlie")

        first = self.client.post("/api/v1/chats/dm", json={"login": "bob"}, headers=self.headers(alice))
        second = self.client.post("/api/v1/chats/dm", json={"login": "alice"}, headers=self.headers(bob))
        private = self.client.get("/api/v1/chats/dm", headers=self.headers(charlie))

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(private.json(), [])

    def test_blocking_hides_contact_and_prevents_new_direct_chats(self) -> None:
        alice = self.register_and_login("alice")
        bob = self.register_and_login("bob")
        self.client.post("/api/v1/chats/dm", json={"login": "bob"}, headers=self.headers(alice))

        blocked = self.client.post("/api/v1/users/bob/block", headers=self.headers(alice))
        search = self.client.get("/api/v1/users/search", params={"q": "bob"}, headers=self.headers(alice))
        new_chat = self.client.post(
            "/api/v1/chats/dm", json={"login": "bob"}, headers=self.headers(alice)
        )

        self.assertEqual(blocked.status_code, 204, blocked.text)
        self.assertEqual(search.json(), [])
        self.assertEqual(new_chat.status_code, 403, new_chat.text)


if __name__ == "__main__":
    unittest.main()

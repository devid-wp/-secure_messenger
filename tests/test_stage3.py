from __future__ import annotations

import tempfile
import unittest
from uuid import uuid4
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

    def test_message_history_uses_chat_bound_cursor_pagination(self) -> None:
        alice_token = self.register_and_login("alice")
        self.register_and_login("bob")
        self.register_and_login("charlie")
        headers = self.headers(alice_token)
        chat = self.client.post(
            "/api/v1/chats/dm",
            json={"login": "bob"},
            headers=headers,
        ).json()

        with self.client.websocket_connect(
            "/api/v1/realtime/ws",
            subprotocols=[f"bearer.{alice_token}"],
        ) as websocket:
            for number in range(5):
                websocket.send_json(
                    {"chat_id": chat["id"], "text": f"message-{number}"}
                )
                websocket.receive_json()

        first = self.client.get(
            f"/api/v1/chats/{chat['id']}/messages",
            params={"limit": 2},
            headers=headers,
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(
            [item["content"] for item in first.json()["items"]],
            ["message-3", "message-4"],
        )
        self.assertTrue(first.json()["has_more"])

        second = self.client.get(
            f"/api/v1/chats/{chat['id']}/messages",
            params={"limit": 2, "cursor": first.json()["next_cursor"]},
            headers=headers,
        )
        self.assertEqual(
            [item["content"] for item in second.json()["items"]],
            ["message-1", "message-2"],
        )
        self.assertTrue(second.json()["has_more"])

        other_chat = self.client.post(
            "/api/v1/chats/dm",
            json={"login": "charlie"},
            headers=headers,
        ).json()
        invalid = self.client.get(
            f"/api/v1/chats/{other_chat['id']}/messages",
            params={"cursor": first.json()["next_cursor"]},
            headers=headers,
        )
        self.assertEqual(invalid.status_code, 400)

    def test_client_uuid_makes_message_send_idempotent(self) -> None:
        alice_token = self.register_and_login("alice")
        self.register_and_login("bob")
        headers = self.headers(alice_token)
        chat = self.client.post(
            "/api/v1/chats/dm",
            json={"login": "bob"},
            headers=headers,
        ).json()
        client_id = str(uuid4())
        payload = {
            "chat_id": chat["id"],
            "text": "send once",
            "client_id": client_id,
        }

        with self.client.websocket_connect(
            "/api/v1/realtime/ws",
            subprotocols=[f"bearer.{alice_token}"],
        ) as websocket:
            websocket.send_json(payload)
            first = websocket.receive_json()

        with self.client.websocket_connect(
            "/api/v1/realtime/ws",
            subprotocols=[f"bearer.{alice_token}"],
        ) as websocket:
            websocket.send_json(payload)
            second = websocket.receive_json()

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["server_seq"], second["server_seq"])
        self.assertEqual(first["client_id"], client_id)
        self.assertEqual(first["server_seq"], 1)
        history = self.client.get(
            f"/api/v1/chats/{chat['id']}/messages",
            headers=headers,
        ).json()
        self.assertEqual(len(history["items"]), 1)

    def test_server_sequence_is_monotonic_per_chat(self) -> None:
        token = self.register_and_login("alice")
        self.register_and_login("bob")
        chat = self.client.post(
            "/api/v1/chats/dm",
            json={"login": "bob"},
            headers=self.headers(token),
        ).json()
        with self.client.websocket_connect(
            "/api/v1/realtime/ws",
            subprotocols=[f"bearer.{token}"],
        ) as websocket:
            sequences = []
            for text in ("one", "two", "three"):
                websocket.send_json(
                    {
                        "chat_id": chat["id"],
                        "text": text,
                        "client_id": str(uuid4()),
                    }
                )
                sequences.append(websocket.receive_json()["server_seq"])
        self.assertEqual(sequences, [1, 2, 3])

    def test_delivery_and_read_receipts_are_confirmed_to_sender(self) -> None:
        alice_token = self.register_and_login("alice")
        bob_token = self.register_and_login("bob")
        chat = self.client.post(
            "/api/v1/chats/dm",
            json={"login": "bob"},
            headers=self.headers(alice_token),
        ).json()
        with (
            self.client.websocket_connect(
                "/api/v1/realtime/ws",
                subprotocols=[f"bearer.{alice_token}"],
            ) as alice,
            self.client.websocket_connect(
                "/api/v1/realtime/ws",
                subprotocols=[f"bearer.{bob_token}"],
            ) as bob,
        ):
            alice.send_json(
                {
                    "type": "send_message",
                    "chat_id": chat["id"],
                    "text": "receipt test",
                    "client_id": str(uuid4()),
                }
            )
            sent = alice.receive_json()
            incoming = bob.receive_json()
            self.assertEqual(sent["type"], "message_ack")
            self.assertEqual(sent["status"], "sent")

            bob.send_json(
                {
                    "type": "delivered",
                    "chat_id": chat["id"],
                    "server_seq": incoming["server_seq"],
                }
            )
            delivered = alice.receive_json()
            self.assertEqual(delivered["status"], "delivered")

            bob.send_json(
                {
                    "type": "read",
                    "chat_id": chat["id"],
                    "server_seq": incoming["server_seq"],
                }
            )
            read = alice.receive_json()
            self.assertEqual(read["status"], "read")

        history = self.client.get(
            f"/api/v1/chats/{chat['id']}/messages",
            headers=self.headers(alice_token),
        ).json()
        self.assertEqual(history["items"][0]["status"], "read")


if __name__ == "__main__":
    unittest.main()

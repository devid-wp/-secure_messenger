from __future__ import annotations

import base64
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.test_foundation import run_migrations, sqlite_async_url


class E2eeDeliveryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.database_path = Path(self.temporary_directory.name) / "e2ee.db"
        run_migrations(self.database_path)
        self.client_context = TestClient(
            create_app(
                Settings(
                    environment="test",
                    database_url=sqlite_async_url(self.database_path),
                )
            )
        )
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary_directory.cleanup()

    def register_and_login(self, login: str) -> tuple[str, str]:
        self.client.post(
            "/api/v1/auth/register",
            json={"login": login, "password": "password-123"},
        )
        response = self.client.post(
            "/api/v1/auth/login",
            json={"login": login, "password": "password-123"},
        )
        return response.json()["token"], response.json()["device_id"]

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def encoded(value: bytes) -> str:
        return base64.b64encode(value).decode()

    def publish_identity(self, token: str, seed: int) -> dict:
        response = self.client.put(
            "/api/v1/e2ee/identity",
            headers=self.headers(token),
            json={"identity_key": self.encoded(bytes([seed]) * 32)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_device_identity_is_public_and_immutable(self) -> None:
        alice, device_id = self.register_and_login("alice")
        bob, _ = self.register_and_login("bob")
        identity = self.publish_identity(alice, 1)
        self.assertEqual(identity["device_id"], device_id)
        self.assertEqual(len(identity["fingerprint"]), 64)

        repeated = self.client.put(
            "/api/v1/e2ee/identity",
            headers=self.headers(alice),
            json={"identity_key": self.encoded(bytes([1]) * 32)},
        )
        changed = self.client.put(
            "/api/v1/e2ee/identity",
            headers=self.headers(alice),
            json={"identity_key": self.encoded(bytes([2]) * 32)},
        )
        directory = self.client.get(
            "/api/v1/e2ee/users/alice/identities",
            headers=self.headers(bob),
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(directory.json()[0]["fingerprint"], identity["fingerprint"])

    def test_key_packages_are_claimed_once_per_active_device(self) -> None:
        alice, _ = self.register_and_login("alice")
        bob, _ = self.register_and_login("bob")
        self.publish_identity(alice, 1)
        self.publish_identity(bob, 2)
        package = bytes(range(64))
        published = self.client.post(
            "/api/v1/e2ee/key-packages",
            headers=self.headers(bob),
            json={
                "key_packages": [self.encoded(package)],
                "cipher_suite": 1,
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(days=7)
                ).isoformat(),
            },
        )
        self.assertEqual(published.status_code, 201, published.text)
        first = self.client.post(
            "/api/v1/e2ee/users/bob/key-packages/claim",
            headers=self.headers(alice),
        )
        second = self.client.post(
            "/api/v1/e2ee/users/bob/key-packages/claim",
            headers=self.headers(alice),
        )
        self.assertEqual(len(first.json()), 1)
        self.assertEqual(base64.b64decode(first.json()[0]["key_package"]), package)
        self.assertEqual(second.json(), [])

    def test_key_package_inventory_tracks_claims(self) -> None:
        alice, _ = self.register_and_login("alice-inventory")
        bob, _ = self.register_and_login("bob-inventory")
        self.publish_identity(alice, 3)
        self.publish_identity(bob, 4)
        payload = {
            "key_packages": [self.encoded(bytes([index]) * 64) for index in (5, 6)],
            "cipher_suite": 1,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        }
        published = self.client.post(
            "/api/v1/e2ee/key-packages", headers=self.headers(bob), json=payload
        )
        self.assertEqual(published.status_code, 201, published.text)
        before = self.client.get(
            "/api/v1/e2ee/key-packages/status", headers=self.headers(bob)
        )
        self.assertEqual(before.json(), {"available": 2, "cipher_suite": 1})
        self.client.post(
            "/api/v1/e2ee/users/bob-inventory/key-packages/claim",
            headers=self.headers(alice),
        )
        after = self.client.get(
            "/api/v1/e2ee/key-packages/status", headers=self.headers(bob)
        )
        self.assertEqual(after.json(), {"available": 1, "cipher_suite": 1})

    def test_unsupported_ciphersuite_is_rejected(self) -> None:
        token, _ = self.register_and_login("wrong-suite")
        self.publish_identity(token, 7)
        response = self.client.post(
            "/api/v1/e2ee/key-packages",
            headers=self.headers(token),
            json={
                "key_packages": [self.encoded(bytes([8]) * 64)],
                "cipher_suite": 2,
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_revoked_device_is_removed_from_identity_directory(self) -> None:
        alice, alice_device = self.register_and_login("alice")
        bob, _ = self.register_and_login("bob")
        self.publish_identity(alice, 1)
        revoked = self.client.delete(
            f"/api/v1/auth/devices/{alice_device}",
            headers=self.headers(alice),
        )
        self.assertEqual(revoked.status_code, 204)
        directory = self.client.get(
            "/api/v1/e2ee/users/alice/identities",
            headers=self.headers(bob),
        )
        self.assertEqual(directory.status_code, 404)

    def test_mls_envelopes_are_opaque_targeted_and_idempotent(self) -> None:
        alice, alice_device = self.register_and_login("alice-envelope")
        bob, bob_device = self.register_and_login("bob-envelope")
        self.publish_identity(alice, 11)
        self.publish_identity(bob, 12)
        chat_response = self.client.post(
            "/api/v1/chats/dm",
            headers=self.headers(alice),
            json={"login": "bob-envelope"},
        )
        self.assertEqual(chat_response.status_code, 200, chat_response.text)
        chat_id = chat_response.json()["id"]
        ciphertext = b"opaque-openmls-wire-data"
        body = {
            "epoch": 1,
            "content_type": "application",
            "payload": self.encoded(ciphertext),
        }
        first = self.client.post(
            f"/api/v1/e2ee/chats/{chat_id}/envelopes",
            headers=self.headers(alice),
            json=body,
        )
        duplicate = self.client.post(
            f"/api/v1/e2ee/chats/{chat_id}/envelopes",
            headers=self.headers(alice),
            json=body,
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(duplicate.json()["id"], first.json()["id"])
        inbox = self.client.get(
            f"/api/v1/e2ee/chats/{chat_id}/envelopes",
            headers=self.headers(bob),
        )
        self.assertEqual(len(inbox.json()), 1)
        self.assertEqual(base64.b64decode(inbox.json()[0]["payload"]), ciphertext)

        welcome = self.client.post(
            f"/api/v1/e2ee/chats/{chat_id}/envelopes",
            headers=self.headers(alice),
            json={
                "epoch": 1,
                "content_type": "welcome",
                "payload": self.encoded(b"opaque-welcome"),
                "recipient_device_id": bob_device,
            },
        )
        self.assertEqual(welcome.status_code, 201, welcome.text)
        alice_inbox = self.client.get(
            f"/api/v1/e2ee/chats/{chat_id}/envelopes",
            headers=self.headers(alice),
        ).json()
        self.assertFalse(any(item["content_type"] == "welcome" for item in alice_inbox))
        self.assertNotEqual(alice_device, bob_device)

    def test_schema_has_no_plaintext_messages_receipts_or_group_names(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            chat_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(chats)")
            }
            media_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(media_objects)")
            }
        self.assertNotIn("messages", tables)
        self.assertNotIn("message_receipts", tables)
        self.assertNotIn("name", chat_columns)
        self.assertNotIn("next_message_seq", chat_columns)
        self.assertIn("chat_id", media_columns)

    def test_plaintext_fields_are_rejected_and_never_persisted(self) -> None:
        alice, _ = self.register_and_login("privacy-alice")
        bob, _ = self.register_and_login("privacy-bob")
        chat_id = self.client.post(
            "/api/v1/chats/dm", headers=self.headers(alice), json={"login": "privacy-bob"}
        ).json()["id"]
        sentinel = "SERVER_MUST_NEVER_RECEIVE_THIS_PLAINTEXT"
        rejected = self.client.post(
            f"/api/v1/e2ee/chats/{chat_id}/envelopes",
            headers=self.headers(alice),
            json={"epoch": 0, "content_type": "application", "payload": self.encoded(b"opaque"), "content": sentinel},
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)
        with self.client.websocket_connect(
            "/api/v1/realtime/ws", subprotocols=[f"bearer.{bob}"]
        ) as websocket:
            websocket.send_json({"type": "send_message", "content": sentinel})
            self.assertEqual(websocket.receive_json()["type"], "error")
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM mls_envelopes").fetchone()[0], 0)

    def test_group_name_is_rejected_by_routing_api(self) -> None:
        token, _ = self.register_and_login("opaque-group-owner")
        rejected = self.client.post(
            "/api/v1/chats/groups",
            headers=self.headers(token),
            json={"name": "server must not parse this"},
        )
        created = self.client.post(
            "/api/v1/chats/groups",
            headers=self.headers(token),
            json={},
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertNotIn("name", created.json())
        self.assertNotIn("last_message", created.json())
        self.assertNotIn("unread_count", created.json())

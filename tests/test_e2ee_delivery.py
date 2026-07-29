from __future__ import annotations

import base64
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
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "e2ee.db"
        run_migrations(database_path)
        self.client_context = TestClient(
            create_app(
                Settings(
                    environment="test",
                    database_url=sqlite_async_url(database_path),
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

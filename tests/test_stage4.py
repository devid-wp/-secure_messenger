from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.test_foundation import run_migrations, sqlite_async_url


class GroupApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "group-chat.db"
        run_migrations(self.database_path)
        settings = Settings(environment="test", database_url=sqlite_async_url(self.database_path))
        self.client_context = TestClient(create_app(settings))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary_directory.cleanup()

    def register_and_login(self, login: str) -> str:
        self.client.post("/api/v1/auth/register", json={"login": login, "password": "password-123"})
        response = self.client.post("/api/v1/auth/login", json={"login": login, "password": "password-123"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def create_group(self, token: str, members: list[str] | None = None) -> dict:
        response = self.client.post(
            "/api/v1/chats/groups",
            headers=self.headers(token),
            json={"member_logins": members or []},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_owner_creates_and_updates_group_profile(self) -> None:
        owner = self.register_and_login("owner")
        self.register_and_login("bob")
        group = self.create_group(owner, members=["bob"])
        updated = self.client.patch(
            f"/api/v1/chats/groups/{group['id']}",
            headers=self.headers(owner),
            json={"avatar_url": None},
        )

        self.assertEqual(group["members"], ["bob", "owner"])
        self.assertEqual(group["member_roles"]["owner"], "owner")
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertIsNone(updated.json()["avatar_url"])

    def test_roles_guard_membership_changes(self) -> None:
        owner = self.register_and_login("owner")
        admin = self.register_and_login("admin")
        self.register_and_login("member")
        group = self.create_group(owner)
        added_admin = self.client.post(
            f"/api/v1/chats/groups/{group['id']}/members",
            headers=self.headers(owner), json={"login": "admin", "role": "admin"},
        )
        added_member = self.client.post(
            f"/api/v1/chats/groups/{group['id']}/members",
            headers=self.headers(admin), json={"login": "member"},
        )
        cannot_remove_owner = self.client.delete(
            f"/api/v1/chats/groups/{group['id']}/members/owner", headers=self.headers(admin)
        )

        self.assertEqual(added_admin.status_code, 200, added_admin.text)
        self.assertEqual(added_member.status_code, 200, added_member.text)
        self.assertEqual(cannot_remove_owner.status_code, 409)

    def test_invitation_can_be_accepted_once(self) -> None:
        owner = self.register_and_login("owner")
        bob = self.register_and_login("bob")
        group = self.create_group(owner)
        invitation = self.client.post(
            f"/api/v1/chats/groups/{group['id']}/invitations",
            headers=self.headers(owner), json={"login": "bob"},
        )
        accepted = self.client.post(
            f"/api/v1/chats/groups/invitations/{invitation.json()['id']}/accept", headers=self.headers(bob)
        )

        self.assertEqual(invitation.status_code, 201, invitation.text)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertIn("bob", accepted.json()["members"])

    def test_owner_can_transfer_ownership_then_leave(self) -> None:
        owner = self.register_and_login("owner")
        bob = self.register_and_login("bob")
        group = self.create_group(owner, members=["bob"])
        transferred = self.client.post(
            f"/api/v1/chats/groups/{group['id']}/owner", headers=self.headers(owner), json={"login": "bob"}
        )
        left = self.client.delete(f"/api/v1/chats/groups/{group['id']}/leave", headers=self.headers(owner))

        self.assertEqual(transferred.status_code, 200, transferred.text)
        self.assertEqual(transferred.json()["member_roles"]["bob"], "owner")
        self.assertEqual(left.status_code, 204, left.text)


if __name__ == "__main__":
    unittest.main()

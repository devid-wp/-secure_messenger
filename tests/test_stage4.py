from __future__ import annotations

from tests.test_stage3 import DirectMessagesApiTests


class GroupApiTests(DirectMessagesApiTests):
    def test_owner_creates_and_updates_group_profile(self) -> None:
        alice = self.register_and_login("alice")
        self.register_and_login("bob")
        created = self.client.post(
            "/api/v1/chats/groups",
            headers=self.headers(alice),
            json={
                "name": "Core team",
                "avatar_url": "https://example.com/team.png",
                "member_logins": ["bob"],
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        group = created.json()
        self.assertEqual(group["members"], ["alice", "bob"])
        self.assertEqual(group["member_roles"]["alice"], "owner")
        self.assertEqual(group["avatar_url"], "https://example.com/team.png")

        updated = self.client.patch(
            f"/api/v1/chats/groups/{group['id']}",
            headers=self.headers(alice),
            json={"name": "Platform team", "avatar_url": None},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["name"], "Platform team")
        self.assertIsNone(updated.json()["avatar_url"])

    def test_owner_adds_and_removes_members_with_role_guards(self) -> None:
        owner = self.register_and_login("owner")
        admin = self.register_and_login("admin")
        self.register_and_login("member")
        group = self.client.post(
            "/api/v1/chats/groups",
            headers=self.headers(owner),
            json={"name": "Ops", "member_logins": []},
        ).json()
        added_admin = self.client.post(
            f"/api/v1/chats/groups/{group['id']}/members",
            headers=self.headers(owner),
            json={"login": "admin", "role": "admin"},
        )
        self.assertEqual(added_admin.status_code, 200, added_admin.text)
        self.assertEqual(added_admin.json()["member_roles"]["admin"], "admin")
        added_member = self.client.post(
            f"/api/v1/chats/groups/{group['id']}/members",
            headers=self.headers(admin),
            json={"login": "member"},
        )
        self.assertEqual(added_member.status_code, 200, added_member.text)

        cannot_remove_owner = self.client.delete(
            f"/api/v1/chats/groups/{group['id']}/members/owner",
            headers=self.headers(admin),
        )
        self.assertEqual(cannot_remove_owner.status_code, 409)
        removed = self.client.delete(
            f"/api/v1/chats/groups/{group['id']}/members/member",
            headers=self.headers(admin),
        )
        self.assertEqual(removed.status_code, 204)

    def test_invitee_accepts_expiring_group_invitation(self) -> None:
        owner = self.register_and_login("owner")
        bob = self.register_and_login("bob")
        group = self.client.post(
            "/api/v1/chats/groups",
            headers=self.headers(owner),
            json={"name": "Invite only"},
        ).json()
        invited = self.client.post(
            f"/api/v1/chats/groups/{group['id']}/invitations",
            headers=self.headers(owner),
            json={"login": "bob"},
        )
        self.assertEqual(invited.status_code, 201, invited.text)
        pending = self.client.get(
            "/api/v1/chats/groups/invitations/pending",
            headers=self.headers(bob),
        )
        self.assertEqual(len(pending.json()), 1)
        accepted = self.client.post(
            f"/api/v1/chats/groups/invitations/{invited.json()['id']}/accept",
            headers=self.headers(bob),
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertIn("bob", accepted.json()["members"])

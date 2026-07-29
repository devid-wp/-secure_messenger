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

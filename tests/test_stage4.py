from __future__ import annotations

from uuid import uuid4

from tests.test_stage3 import DirectMessagesApiTests


class GroupApiTests(DirectMessagesApiTests):
    def send_message(self, token: str, chat_id: int, text: str) -> dict:
        with self.client.websocket_connect(
            "/api/v1/realtime/ws",
            subprotocols=[f"bearer.{token}"],
        ) as websocket:
            websocket.send_json(
                {
                    "type": "send_message",
                    "chat_id": chat_id,
                    "text": text,
                    "client_id": str(uuid4()),
                }
            )
            return websocket.receive_json()

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

    def test_owner_transfers_ownership_then_leaves(self) -> None:
        owner = self.register_and_login("owner")
        bob = self.register_and_login("bob")
        group = self.client.post(
            "/api/v1/chats/groups",
            headers=self.headers(owner),
            json={"name": "Governed", "member_logins": ["bob"]},
        ).json()

        owner_cannot_leave = self.client.delete(
            f"/api/v1/chats/groups/{group['id']}/leave",
            headers=self.headers(owner),
        )
        self.assertEqual(owner_cannot_leave.status_code, 409)

        member_cannot_transfer = self.client.post(
            f"/api/v1/chats/groups/{group['id']}/owner",
            headers=self.headers(bob),
            json={"login": "bob"},
        )
        self.assertEqual(member_cannot_transfer.status_code, 403)

        transferred = self.client.post(
            f"/api/v1/chats/groups/{group['id']}/owner",
            headers=self.headers(owner),
            json={"login": "bob"},
        )
        self.assertEqual(transferred.status_code, 200, transferred.text)
        self.assertEqual(transferred.json()["member_roles"]["bob"], "owner")
        self.assertEqual(transferred.json()["member_roles"]["owner"], "admin")

        left = self.client.delete(
            f"/api/v1/chats/groups/{group['id']}/leave",
            headers=self.headers(owner),
        )
        self.assertEqual(left.status_code, 204, left.text)
        owner_groups = self.client.get(
            "/api/v1/chats/groups",
            headers=self.headers(owner),
        )
        self.assertEqual(owner_groups.json(), [])

    def test_group_changes_create_immutable_system_messages(self) -> None:
        owner = self.register_and_login("owner")
        self.register_and_login("bob")
        group = self.client.post(
            "/api/v1/chats/groups",
            headers=self.headers(owner),
            json={"name": "Audit"},
        ).json()
        added = self.client.post(
            f"/api/v1/chats/groups/{group['id']}/members",
            headers=self.headers(owner),
            json={"login": "bob"},
        )
        self.assertEqual(added.status_code, 200, added.text)

        history = self.client.get(
            f"/api/v1/chats/{group['id']}/messages",
            headers=self.headers(owner),
        ).json()["items"]
        self.assertEqual(history[-1]["kind"], "system")
        self.assertIn("added bob", history[-1]["content"])

        edit = self.client.patch(
            f"/api/v1/chats/{group['id']}/messages/{history[-1]['server_seq']}",
            headers=self.headers(owner),
            json={"content": "tampered"},
        )
        delete = self.client.delete(
            f"/api/v1/chats/{group['id']}/messages/{history[-1]['server_seq']}",
            headers=self.headers(owner),
        )
        self.assertEqual(edit.status_code, 403)
        self.assertEqual(delete.status_code, 403)

    def test_new_member_history_follows_group_policy(self) -> None:
        owner = self.register_and_login("owner")
        bob = self.register_and_login("bob")
        group = self.client.post(
            "/api/v1/chats/groups",
            headers=self.headers(owner),
            json={"name": "Private history"},
        ).json()
        self.send_message(owner, group["id"], "before Bob")
        self.client.post(
            f"/api/v1/chats/groups/{group['id']}/members",
            headers=self.headers(owner),
            json={"login": "bob"},
        )

        bob_history = self.client.get(
            f"/api/v1/chats/{group['id']}/messages",
            headers=self.headers(bob),
        ).json()["items"]
        self.assertNotIn("before Bob", [item["content"] for item in bob_history])

        updated = self.client.patch(
            f"/api/v1/chats/groups/{group['id']}",
            headers=self.headers(owner),
            json={"history_visibility": "all"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        bob_history = self.client.get(
            f"/api/v1/chats/{group['id']}/messages",
            headers=self.headers(bob),
        ).json()["items"]
        self.assertIn("before Bob", [item["content"] for item in bob_history])

    def test_only_owner_changes_history_policy(self) -> None:
        owner = self.register_and_login("owner")
        admin = self.register_and_login("admin")
        group = self.client.post(
            "/api/v1/chats/groups",
            headers=self.headers(owner),
            json={"name": "Policy", "member_logins": ["admin"]},
        ).json()
        self.client.post(
            f"/api/v1/chats/groups/{group['id']}/members",
            headers=self.headers(owner),
            json={"login": "admin", "role": "admin"},
        )
        response = self.client.patch(
            f"/api/v1/chats/groups/{group['id']}",
            headers=self.headers(admin),
            json={"history_visibility": "all"},
        )
        self.assertEqual(response.status_code, 403)

import base64
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_CONFIG = PROJECT_ROOT / "alembic.ini"


def sqlite_async_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def run_migrations(path: Path) -> None:
    config = Config(str(ALEMBIC_CONFIG))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    with mock.patch.dict(
        os.environ,
        {"DATABASE_URL": sqlite_async_url(path), "APP_ENV": "test"},
    ):
        command.upgrade(config, "head")


def png_image(width: int = 900, height: int = 600) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (width, height), (109, 74, 255, 255)).save(
        output,
        format="PNG",
    )
    return output.getvalue()


class StageSixMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.database_path = root / "stage6.db"
        self.media_dir = root / "media"
        run_migrations(self.database_path)
        settings = Settings(
            environment="test",
            database_url=sqlite_async_url(self.database_path),
            upload_dir=root / "uploads",
            media_dir=self.media_dir,
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
        response = self.client.post(
            "/api/v1/auth/login",
            json={"login": login, "password": "password-123"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def create_pack(self, token: str, visibility: str = "private") -> dict:
        response = self.client.post(
            "/api/v1/sticker-packs",
            headers=self.headers(token),
            json={
                "title": "Purple Signals",
                "slug": "purple-signals",
                "visibility": visibility,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def add_sticker(self, token: str, pack_id: str) -> dict:
        response = self.client.post(
            f"/api/v1/sticker-packs/{pack_id}/stickers",
            headers=self.headers(token),
            files={"sticker": ("signal.png", png_image(), "image/png")},
            data={"emoji": "💜"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_private_and_public_sticker_pack_lifecycle(self) -> None:
        owner_token = self.register_and_login("owner")
        viewer_token = self.register_and_login("viewer")
        pack = self.create_pack(owner_token)
        sticker = self.add_sticker(owner_token, pack["id"])

        self.assertEqual(sticker["width"], 512)
        self.assertEqual(sticker["height"], 512)
        self.assertEqual(
            self.client.get(
                sticker["image_url"],
                headers=self.headers(owner_token),
            ).headers["content-type"],
            "image/webp",
        )
        hidden = self.client.get(
            f"/api/v1/sticker-packs/{pack['id']}",
            headers=self.headers(viewer_token),
        )
        self.assertEqual(hidden.status_code, 404)

        published = self.client.patch(
            f"/api/v1/sticker-packs/{pack['id']}",
            headers=self.headers(owner_token),
            json={"visibility": "public"},
        )
        self.assertEqual(published.status_code, 200, published.text)
        subscribed = self.client.post(
            f"/api/v1/sticker-packs/{pack['id']}/subscription",
            headers=self.headers(viewer_token),
        )
        self.assertEqual(subscribed.status_code, 204, subscribed.text)
        library = self.client.get(
            "/api/v1/sticker-packs",
            headers=self.headers(viewer_token),
        ).json()
        self.assertEqual([item["id"] for item in library], [pack["id"]])

    def test_encrypted_attachment_is_stored_and_shared_as_ciphertext(self) -> None:
        alice = self.register_and_login("alice")
        bob = self.register_and_login("bob")
        chat = self.client.post(
            "/api/v1/chats/dm",
            headers=self.headers(alice),
            json={"login": "bob"},
        ).json()
        ciphertext = b"encrypted-content-with-authentication-tag"
        nonce = base64.b64encode(bytes(range(12))).decode()
        upload = self.client.post(
            "/api/v1/media/attachments",
            headers=self.headers(alice),
            files={
                "ciphertext": (
                    "ciphertext.bin",
                    ciphertext,
                    "application/octet-stream",
                )
            },
            data={
                "plaintext_content_type": "image/png",
                "cipher": "AES-256-GCM",
                "nonce": nonce,
                "width": "800",
                "height": "600",
            },
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        attachment = upload.json()
        self.assertTrue(attachment["is_encrypted"])
        self.assertNotIn("key", attachment)

        client_id = str(uuid4())
        envelope = "opaque-mls-application-ciphertext"
        with self.client.websocket_connect(
            "/api/v1/realtime/ws",
            subprotocols=[f"bearer.{alice}"],
        ) as websocket:
            websocket.send_json(
                {
                    "type": "send_message",
                    "kind": "image",
                    "chat_id": chat["id"],
                    "content": "",
                    "attachment_id": attachment["id"],
                    "key_envelope": envelope,
                    "client_id": client_id,
                }
            )
            message = websocket.receive_json()
        self.assertEqual(message["kind"], "image")
        self.assertEqual(message["attachment"]["id"], attachment["id"])
        self.assertEqual(message["key_envelope"], envelope)

        download = self.client.get(
            attachment["content_url"],
            headers=self.headers(bob),
        )
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(download.content, ciphertext)
        stored_files = list(self.media_dir.rglob("*.bin"))
        self.assertEqual(len(stored_files), 1)
        self.assertEqual(stored_files[0].read_bytes(), ciphertext)

    def test_sticker_message_uses_typed_payload(self) -> None:
        alice = self.register_and_login("alice")
        self.register_and_login("bob")
        chat = self.client.post(
            "/api/v1/chats/dm",
            headers=self.headers(alice),
            json={"login": "bob"},
        ).json()
        pack = self.create_pack(alice)
        sticker = self.add_sticker(alice, pack["id"])
        with self.client.websocket_connect(
            "/api/v1/realtime/ws",
            subprotocols=[f"bearer.{alice}"],
        ) as websocket:
            websocket.send_json(
                {
                    "type": "send_message",
                    "kind": "sticker",
                    "chat_id": chat["id"],
                    "content": "",
                    "sticker_id": sticker["id"],
                    "client_id": str(uuid4()),
                }
            )
            message = websocket.receive_json()
        self.assertEqual(message["kind"], "sticker")
        self.assertEqual(message["content"], "")
        self.assertEqual(message["sticker"]["id"], sticker["id"])

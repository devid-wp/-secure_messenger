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
        visible_image = self.client.get(
            sticker["image_url"],
            headers=self.headers(viewer_token),
        )
        self.assertEqual(visible_image.status_code, 200, visible_image.text)

    def test_encrypted_attachment_is_stored_and_shared_as_ciphertext(self) -> None:
        alice = self.register_and_login("alice")
        bob = self.register_and_login("bob")
        charlie = self.register_and_login("charlie")
        chat = self.client.post(
            "/api/v1/chats/dm",
            headers=self.headers(alice),
            json={"login": "bob"},
        ).json()
        ciphertext = b"encrypted-content-with-authentication-tag"
        rejected = self.client.post(
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
                "chat_id": str(chat["id"]),
                "plaintext_content_type": "image/png",
                "cipher": "AES-256-GCM",
            },
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)
        upload = self.client.post(
            "/api/v1/media/attachments", headers=self.headers(alice),
            files={"ciphertext": ("ciphertext.bin", ciphertext, "application/octet-stream")},
            data={"chat_id": str(chat["id"])},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        attachment = upload.json()
        self.assertTrue(attachment["is_encrypted"])
        self.assertNotIn("key", attachment)
        self.assertNotIn("name", attachment)
        self.assertNotIn("media_type", attachment)
        # Routing metadata only — no plaintext-leaking fields.
        self.assertEqual(
            set(attachment.keys()),
            {"id", "purpose", "size_bytes", "sha256", "is_encrypted", "content_url"},
        )

        with self.client.websocket_connect(
            "/api/v1/realtime/ws",
            subprotocols=[f"bearer.{alice}"],
        ) as websocket:
            websocket.send_json(
                {
                    "type": "send_message",
                    "content": "plaintext is forbidden",
                }
            )
            self.assertEqual(websocket.receive_json()["type"], "error")

        download = self.client.get(
            attachment["content_url"],
            headers=self.headers(bob),
        )
        self.assertEqual(download.status_code, 200, download.text)
        self.assertEqual(download.content, ciphertext)
        # Ciphertext is served opaque with cache disabled, so a Service
        # Worker or shared cache can never capture the plaintext side of
        # the file.
        self.assertEqual(download.headers["content-type"], "application/octet-stream")
        self.assertEqual(download.headers["cache-control"], "private, no-store")
        self.assertEqual(download.headers["x-content-type-options"], "nosniff")
        forbidden = self.client.get(
            attachment["content_url"],
            headers=self.headers(charlie),
        )
        self.assertEqual(forbidden.status_code, 404)
        stored_files = list(self.media_dir.rglob("*.bin"))
        self.assertEqual(len(stored_files), 1)
        self.assertEqual(stored_files[0].read_bytes(), ciphertext)

    def test_attachment_upload_rejects_filename_and_key_form_fields(self) -> None:
        alice = self.register_and_login("alice")
        self.register_and_login("bob")
        chat = self.client.post(
            "/api/v1/chats/dm",
            headers=self.headers(alice),
            json={"login": "bob"},
        ).json()
        ciphertext = b"\x00" * 32 + b"ciphertext-with-gcm-tag"
        for forbidden in ("filename", "key", "nonce", "sha256", "object_id", "media_type", "is_encrypted"):
            response = self.client.post(
                "/api/v1/media/attachments",
                headers=self.headers(alice),
                files={"ciphertext": ("ciphertext.bin", ciphertext, "application/octet-stream")},
                data={"chat_id": str(chat["id"]), forbidden: "leak"},
            )
            self.assertEqual(response.status_code, 422, (forbidden, response.text))

    def test_attachment_size_limit_is_checked_before_storage(self) -> None:
        alice = self.register_and_login("size-alice")
        self.register_and_login("size-bob")
        chat = self.client.post(
            "/api/v1/chats/dm",
            headers=self.headers(alice),
            json={"login": "size-bob"},
        ).json()
        with mock.patch("app.routers.media.MAX_ATTACHMENT_BYTES", 32):
            response = self.client.post(
                "/api/v1/media/attachments",
                headers=self.headers(alice),
                files={"ciphertext": ("ciphertext.bin", b"x" * 33, "application/octet-stream")},
                data={"chat_id": str(chat["id"])},
            )
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(list(self.media_dir.rglob("*.bin")), [])

    def test_sticker_plaintext_websocket_payload_is_rejected(self) -> None:
        alice = self.register_and_login("alice")
        self.register_and_login("bob")
        chat = self.client.post(
            "/api/v1/chats/dm",
            headers=self.headers(alice),
            json={"login": "bob"},
        ).json()
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
                    "sticker_id": str(uuid4()),
                    "client_id": str(uuid4()),
                }
            )
            message = websocket.receive_json()
        self.assertEqual(message["type"], "error")
        self.assertIn("opaque MLS envelopes", message["detail"])
        self.assertNotIn("kind", message)

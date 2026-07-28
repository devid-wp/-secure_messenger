import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, create_mock_engine

from app.core.config import Settings
from app.main import create_app
from app.models import Base


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_CONFIG = PROJECT_ROOT / "alembic.ini"


def sqlite_async_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def run_migrations(path: Path) -> None:
    config = Config(str(ALEMBIC_CONFIG))
    config.set_main_option(
        "script_location",
        str(PROJECT_ROOT / "migrations"),
    )
    with mock.patch.dict(
        os.environ,
        {"DATABASE_URL": sqlite_async_url(path), "APP_ENV": "test"},
    ):
        command.upgrade(config, "head")


def create_stage_zero_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE NOT NULL,
                hash BLOB NOT NULL,
                salt BLOB NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK (type IN ('dm', 'group')),
                name TEXT,
                created_by TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE chat_members (
                chat_id INTEGER NOT NULL,
                login TEXT NOT NULL,
                joined_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, login),
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );
            """
        )
        connection.execute(
            "INSERT INTO users (login, hash, salt) VALUES (?, ?, ?)",
            ("admin ", b"hash", b"salt"),
        )
        connection.executemany(
            "INSERT INTO chats (id, type, name, created_by) VALUES (?, 'dm', NULL, ?)",
            [(1, "admin "), (2, "admin ")],
        )
        connection.executemany(
            "INSERT INTO chat_members (chat_id, login) VALUES (?, ?)",
            [(1, "admin "), (1, "Bob"), (2, "admin "), (2, "Diana")],
        )
        connection.executemany(
            """
            INSERT INTO messages (id, chat_id, sender, content, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (1, 1, "admin ", "д", "2026-06-15 13:50:27"),
                (2, 2, "admin ", "д", "2026-06-15 13:50:32"),
                (3, 2, "admin ", "ж", "2026-06-15 13:50:33"),
                (4, 2, "admin ", "ж", "2026-06-15 13:50:35"),
            ],
        )
        connection.commit()
    finally:
        connection.close()


class FoundationMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "test.db"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_clean_database_upgrade(self) -> None:
        run_migrations(self.database_path)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()[0],
                "20260728_09",
            )
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )
        finally:
            connection.close()

    def test_stage_zero_data_is_preserved_with_foreign_keys(self) -> None:
        create_stage_zero_database(self.database_path)
        run_migrations(self.database_path)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                4,
            )
            placeholders = connection.execute(
                """
                SELECT login
                FROM users
                WHERE is_placeholder = true
                ORDER BY login
                """
            ).fetchall()
            self.assertEqual(placeholders, [("Bob",), ("Diana",)])
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM chat_members"
                ).fetchone()[0],
                4,
            )
        finally:
            connection.close()

    def test_models_declare_checks_and_foreign_keys(self) -> None:
        constraints = [
            constraint
            for table in Base.metadata.tables.values()
            for constraint in table.constraints
        ]
        self.assertGreaterEqual(
            sum(isinstance(item, ForeignKeyConstraint) for item in constraints),
            5,
        )
        self.assertGreaterEqual(
            sum(isinstance(item, CheckConstraint) for item in constraints),
            5,
        )

    def test_production_rejects_sqlite(self) -> None:
        settings = Settings(
            environment="production",
            database_url=sqlite_async_url(self.database_path),
        )
        with self.assertRaises(RuntimeError):
            settings.validate()

    def test_models_compile_for_postgresql(self) -> None:
        statements: list[str] = []
        engine = create_mock_engine(
            "postgresql+psycopg://",
            lambda sql, *_args, **_kwargs: statements.append(str(sql.compile())),
        )
        Base.metadata.create_all(engine)
        rendered = "\n".join(statements)
        self.assertIn("CREATE TABLE users", rendered)
        self.assertIn("CREATE TABLE chat_members", rendered)
        self.assertIn("FOREIGN KEY", rendered)

    def test_production_requires_redis(self) -> None:
        settings = Settings(
            environment="production",
            database_url="postgresql+psycopg://user:password@db/app",
        )
        with self.assertRaises(RuntimeError):
            settings.validate()


class VersionedApiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "api.db"
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

    def _register_and_login(self, login: str) -> str:
        response = self.client.post(
            "/api/v1/auth/register",
            json={"login": login, "password": "password-123"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post(
            "/api/v1/auth/login",
            json={"login": login, "password": "password-123"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    def test_auth_chat_message_and_websocket(self) -> None:
        alice_token = self._register_and_login("alice")
        bob_token = self._register_and_login("bob")
        alice_headers = {"Authorization": f"Bearer {alice_token}"}

        users = self.client.get("/api/v1/users", headers=alice_headers)
        self.assertEqual(users.status_code, 200)
        self.assertEqual([user["login"] for user in users.json()], ["bob"])

        chat_response = self.client.post(
            "/api/v1/chats/dm",
            headers=alice_headers,
            json={"login": "bob"},
        )
        self.assertEqual(chat_response.status_code, 200, chat_response.text)
        chat = chat_response.json()
        self.assertEqual(chat["members"], ["alice", "bob"])

        with (
            self.client.websocket_connect(
                "/api/v1/realtime/ws",
                subprotocols=[f"bearer.{alice_token}"],
            ) as alice_ws,
            self.client.websocket_connect(
                "/api/v1/realtime/ws",
                subprotocols=[f"bearer.{bob_token}"],
            ) as bob_ws,
        ):
            alice_ws.send_json({"chat_id": chat["id"], "text": "hello"})
            alice_event = alice_ws.receive_json()
            bob_event = bob_ws.receive_json()
        self.assertEqual(alice_event["id"], bob_event["id"])
        self.assertEqual(alice_event["type"], "message_ack")
        self.assertEqual(bob_event["type"], "message")
        self.assertEqual(alice_event["sender"], "alice")

        messages = self.client.get(
            f"/api/v1/chats/{chat['id']}/messages",
            headers=alice_headers,
        )
        self.assertEqual(messages.status_code, 200)
        self.assertEqual(messages.json()["items"][0]["content"], "hello")

        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertIn("/api/v1/auth/login", paths)
        self.assertNotIn("/login", paths)

    def test_logout_and_device_revocation(self) -> None:
        token = self._register_and_login("carol")
        headers = {"Authorization": f"Bearer {token}"}
        devices = self.client.get("/api/v1/auth/devices", headers=headers)
        self.assertEqual(devices.status_code, 200, devices.text)
        device_id = devices.json()[0]["id"]

        revoked = self.client.delete(
            f"/api/v1/auth/devices/{device_id}", headers=headers
        )
        self.assertEqual(revoked.status_code, 204, revoked.text)
        self.assertEqual(
            self.client.get("/api/v1/users", headers=headers).status_code,
            401,
        )

        token = self.client.post(
            "/api/v1/auth/login",
            json={"login": "carol", "password": "password-123"},
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(
            self.client.post("/api/v1/auth/logout", headers=headers).status_code,
            204,
        )
        self.assertEqual(
            self.client.get("/api/v1/users", headers=headers).status_code,
            401,
        )

    def test_new_passwords_use_argon2id(self) -> None:
        self._register_and_login("dave")
        connection = sqlite3.connect(self.database_path)
        try:
            password_hash, password_salt = connection.execute(
                "SELECT password_hash, password_salt FROM users WHERE login = 'dave'"
            ).fetchone()
        finally:
            connection.close()
        self.assertTrue(bytes(password_hash).startswith(b"$argon2id$"))
        self.assertEqual(password_salt, b"")


if __name__ == "__main__":
    unittest.main()

import sqlite3
from pathlib import Path
from typing import Any, Optional


class Database:
    """Класс для работы с SQLite базой данных secure_messenger"""

    def __init__(self, db_path: str = "secure_messenger.db"):
        """Инициализирует подключение к БД"""
        self.db_path = Path(db_path)
        self.connection: Optional[sqlite3.Connection] = None
        self._connect()

    def _connect(self) -> None:
        """Создаёт подключение к БД"""
        self.connection = sqlite3.connect(str(self.db_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def create_tables(self) -> None:
        """Создаёт таблицы если они не существуют"""
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")

        schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with open(schema_path, "r", encoding="utf-8") as f:
            schema = f.read()

        cursor = self.connection.cursor()
        cursor.executescript(schema)
        self.connection.commit()

    # ----------------- users -----------------

    def save_user(self, login: str, hash_bytes: bytes, salt_bytes: bytes) -> bool:
        """Сохраняет пользователя. False если логин уже занят."""
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO users (login, hash, salt) VALUES (?, ?, ?)",
                (login, hash_bytes, salt_bytes),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_user(self, login: str) -> Optional[dict[str, Any]]:
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT login, hash, salt FROM users WHERE login = ?", (login,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def user_exists(self, login: str) -> bool:
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute("SELECT 1 FROM users WHERE login = ? LIMIT 1", (login,))
        return cursor.fetchone() is not None

    def list_users(self) -> list[dict[str, Any]]:
        """Все зарегистрированные пользователи (без hash/salt)."""
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute("SELECT login, created_at FROM users ORDER BY login")
        return [dict(row) for row in cursor.fetchall()]

    # ----------------- chats -----------------

    def create_chat(
        self, chat_type: str, name: Optional[str], creator: str, members: list[str]
    ) -> dict[str, Any]:
        """Создать чат и сразу добавить всех участников."""
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        # Создатель всегда в списке участников.
        all_members = {creator, *members}
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO chats (type, name, created_by) VALUES (?, ?, ?)",
            (chat_type, name, creator),
        )
        chat_id = cursor.lastrowid
        cursor.executemany(
            "INSERT OR IGNORE INTO chat_members (chat_id, login) VALUES (?, ?)",
            [(chat_id, m) for m in all_members],
        )
        self.connection.commit()
        return {"id": chat_id, "type": chat_type, "name": name, "members": sorted(all_members)}

    def find_dm_chat(self, login_a: str, login_b: str) -> Optional[dict[str, Any]]:
        """Найти существующий DM между двумя логинами."""
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT c.id, c.type, c.name
            FROM chats c
            WHERE c.type = 'dm'
              AND c.id IN (SELECT chat_id FROM chat_members WHERE login = ?)
              AND c.id IN (SELECT chat_id FROM chat_members WHERE login = ?)
              AND (SELECT COUNT(*) FROM chat_members WHERE chat_id = c.id) = 2
            LIMIT 1
            """,
            (login_a, login_b),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {"id": row["id"], "type": row["type"], "name": row["name"]}

    def get_user_chats(self, login: str) -> list[dict[str, Any]]:
        """Все чаты пользователя + состав участников."""
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT c.id, c.type, c.name, c.created_by
            FROM chats c
            JOIN chat_members m ON m.chat_id = c.id
            WHERE m.login = ?
            ORDER BY c.created_at DESC
            """,
            (login,),
        )
        chats = [dict(row) for row in cursor.fetchall()]
        if not chats:
            return []
        ids = tuple(c["id"] for c in chats)
        placeholders = ",".join("?" * len(ids))
        cursor.execute(
            f"SELECT chat_id, login FROM chat_members WHERE chat_id IN ({placeholders})",
            ids,
        )
        members_by_chat: dict[int, list[str]] = {}
        for row in cursor.fetchall():
            members_by_chat.setdefault(row["chat_id"], []).append(row["login"])
        for chat in chats:
            chat["members"] = sorted(members_by_chat.get(chat["id"], []))
        return chats

    def get_chat_members(self, chat_id: int) -> list[str]:
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT login FROM chat_members WHERE chat_id = ? ORDER BY login",
            (chat_id,),
        )
        return [row["login"] for row in cursor.fetchall()]

    def is_chat_member(self, chat_id: int, login: str) -> bool:
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT 1 FROM chat_members WHERE chat_id = ? AND login = ?",
            (chat_id, login),
        )
        return cursor.fetchone() is not None

    def add_chat_member(self, chat_id: int, login: str) -> bool:
        """Добавить участника. False если уже есть."""
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO chat_members (chat_id, login) VALUES (?, ?)",
                (chat_id, login),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_chat(self, chat_id: int) -> Optional[dict[str, Any]]:
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT id, type, name, created_by FROM chats WHERE id = ?",
            (chat_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        chat = dict(row)
        chat["members"] = self.get_chat_members(chat_id)
        return chat

    # ----------------- messages -----------------

    def save_chat_message(self, chat_id: int, sender: str, content: str) -> int:
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO messages (chat_id, sender, content) VALUES (?, ?, ?)",
            (chat_id, sender, content),
        )
        self.connection.commit()
        return cursor.lastrowid

    def get_chat_messages(self, chat_id: int, limit: int = 50) -> list[dict[str, Any]]:
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, chat_id, sender, content, timestamp
               FROM messages
               WHERE chat_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (chat_id, limit),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    # ----------------- lifecycle -----------------

    def close(self) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

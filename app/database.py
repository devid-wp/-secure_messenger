import sqlite3
from pathlib import Path
from typing import Optional, Dict, List, Any


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

    def create_tables(self) -> None:
        """Создаёт таблицы если они не существуют"""
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")

        schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with open(schema_path, "r") as f:
            schema = f.read()

        cursor = self.connection.cursor()
        cursor.executescript(schema)
        self.connection.commit()

    def save_user(self, login: str, hash_bytes: bytes, salt_bytes: bytes) -> bool:
        """
        Сохраняет пользователя в БД
        
        Args:
            login: логин пользователя
            hash_bytes: хеш пароля (бинарные данные)
            salt_bytes: соль (бинарные данные)
            
        Returns:
            True если успешно, False если пользователь уже существует
        """
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")

        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO users (login, hash, salt) VALUES (?, ?, ?)",
                (login, hash_bytes, salt_bytes)
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_user(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Получает пользователя по логину
        
        Args:
            login: логин пользователя
            
        Returns:
            dict с ключами {"login", "hash", "salt"} или None если не найден
        """
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")

        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT login, hash, salt FROM users WHERE login = ?",
            (login,)
        )
        row = cursor.fetchone()

        if row:
            return dict(row)
        return None

    def save_message(self, sender: str, recipient: str, content: str) -> int:
        """
        Сохраняет сообщение в БД
        
        Args:
            sender: кто отправил
            recipient: кому отправил
            content: текст сообщения
            
        Returns:
            id сообщения
        """
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")

        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO messages (sender, recipient, content) VALUES (?, ?, ?)",
            (sender, recipient, content)
        )
        self.connection.commit()
        return cursor.lastrowid

    def get_messages(self, login: str) -> List[Dict[str, Any]]:
        """
        Получает последние 50 сообщений пользователя (входящие и исходящие)
        
        Args:
            login: логин пользователя
            
        Returns:
            список dict с сообщениями (id, sender, recipient, content, timestamp)
        """
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")

        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT id, sender, recipient, content, timestamp 
               FROM messages 
               WHERE sender = ? OR recipient = ? 
               ORDER BY timestamp DESC 
               LIMIT 50""",
            (login, login)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def user_exists(self, login: str) -> bool:
        """
        Проверяет существует ли пользователь
        
        Args:
            login: логин пользователя
            
        Returns:
            True если пользователь существует, False иначе
        """
        if not self.connection:
            raise RuntimeError("Database connection is not initialized")

        cursor = self.connection.cursor()
        cursor.execute("SELECT 1 FROM users WHERE login = ? LIMIT 1", (login,))
        return cursor.fetchone() is not None

    def close(self) -> None:
        """Закрывает подключение к БД"""
        if self.connection:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

-- Пользователи
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT UNIQUE NOT NULL,
    hash BLOB NOT NULL,
    salt BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Старая таблица сообщений (sender/recipient) удалена при миграции на чаты.
-- Воссоздаём с привязкой к chat_id.
DROP TABLE IF EXISTS messages;

-- Чаты: DM или group
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK (type IN ('dm', 'group')),
    name TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Участники чатов (M:N)
CREATE TABLE IF NOT EXISTS chat_members (
    chat_id INTEGER NOT NULL,
    login TEXT NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, login)
);

-- Сообщения в чатах
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_login ON users(login);
CREATE INDEX IF NOT EXISTS idx_chat_members_login ON chat_members(login);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, timestamp);

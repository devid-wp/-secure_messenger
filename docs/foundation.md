# Этап 2: фундамент backend

## Принятые решения

- FastAPI собран из независимых `APIRouter`: `auth`, `users`, `chats`,
  `messages`, `realtime`.
- Весь публичный HTTP/WebSocket API находится под `/api/v1`.
- SQLAlchemy 2.x работает асинхронно; один `AsyncSession` принадлежит одному
  HTTP request или одной операции WebSocket.
- SQLite используется по умолчанию только для локальной разработки и тестов.
- `APP_ENV=production` требует PostgreSQL URL с драйвером psycopg 3.
- Runtime не вызывает `create_all()` и не исполняет SQL-файл схемы.
- Alembic — единственный источник создания и изменения схемы.

## Целостность данных

ORM и Alembic задают:

- UNIQUE для `users.login`;
- CHECK для непустого login;
- CHECK, запрещающий активный placeholder;
- CHECK для типа чата и роли участника;
- CHECK длины сообщения от 1 до 16 384 символов;
- составной PRIMARY KEY `(chat_id, user_id)` для membership;
- FK creator → user;
- FK member → user и chat;
- FK message sender → user и chat;
- `CASCADE` только для дочерних данных чата;
- `RESTRICT` для удаления пользователя, на которого ссылается история.

## Миграция stage 0

Revision `20260726_01`:

1. Создаёт constrained replacement tables.
2. Копирует пользователей.
3. Создаёт неактивных placeholder users для legacy logins без аккаунта.
4. Переводит строковые `login/sender/created_by` в числовые user IDs.
5. Копирует чаты, membership и сообщения.
6. Сравнивает количество исходных и целевых строк.
7. Только после проверки заменяет таблицы.
8. Сохраняет `messages_legacy` как архив, исключённый из autogenerate.

Перед применением к рабочей БД создана резервная копия
`backups/secure_messenger-before-stage2-20260726.db`.

## Конфигурация

| Переменная | Назначение |
|---|---|
| `APP_ENV` | `development`, `test` или `production` |
| `DATABASE_URL` | SQLAlchemy async URL |
| `CORS_ORIGINS` | Разделённый запятыми список origin |
| `SQL_ECHO` | Локальный вывод SQL |

Примеры находятся в `.env.example`.

## Пока не входит в этот этап

- E2EE;
- PostgreSQL integration test в CI.

Эти пункты не следует смешивать с foundation migration: для каждого нужен
отдельный revision и отдельный набор security-тестов.
## Sessions, Redis and passwords

- New password verifiers use Argon2id with `m=19456`, `t=2`, `p=1`.
- Successful login transparently upgrades a legacy PBKDF2 verifier.
- Redis stores only a SHA-256 lookup key for each bearer token and enforces TTL.
- Sessions are bound to persistent device records. Logout revokes one session;
  device revocation removes every session belonging to the device.
- Redis fixed-window counters limit login and authenticated API requests.
- Redis Pub/Sub distributes realtime events between API processes, while shared
  presence counters track connections.
- Development can use process-local stores. Production requires `REDIS_URL`.

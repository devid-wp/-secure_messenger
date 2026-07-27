# Secure Messenger

Мессенджер на FastAPI, SQLAlchemy, PostgreSQL/SQLite и React.

> Текущая реализация ещё не содержит E2EE и хранит сообщения в открытом виде.
> Нормативная модель безопасности находится в [docs/README.md](docs/README.md).

## Backend

```text
app/
  core/config.py       environment и DATABASE_URL
  db.py                async SQLAlchemy engine и session factory
  models.py            ORM-модели, CHECK, UNIQUE и FOREIGN KEY
  schemas.py           модели API
  dependencies.py      request-scoped DB и authentication dependency
  routers/
    auth.py            /api/v1/auth
    users.py           /api/v1/users
    chats.py           /api/v1/chats
    messages.py        /api/v1/chats/{id}/messages
    realtime.py        /api/v1/realtime/ws
  services/            Redis sessions, rate limiting, realtime, serializers
  main.py              сборка FastAPI
migrations/            Alembic revisions
```

Подробности фундамента: [docs/foundation.md](docs/foundation.md).

## Локальный запуск с SQLite

Команды выполняются из корня репозитория:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.main
```

По умолчанию используется `secure_messenger.db` в корне проекта. Приложение
не создаёт таблицы при импорте: перед запуском всегда выполняется Alembic.

## PostgreSQL

Для локальной проверки PostgreSQL добавлен `compose.yaml`:

```powershell
docker compose up -d db
docker compose up -d redis
$env:DATABASE_URL = "postgresql+psycopg://secure_messenger:local-development-only@localhost:5432/secure_messenger"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.main
```

В production необходимо установить:

```text
APP_ENV=production
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
REDIS_URL=redis://HOST:6379/0
```

При `APP_ENV=production` приложение отклоняет SQLite-конфигурацию.

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend обращается к versioned API `/api/v1`. Другой origin backend задаётся
через `VITE_API_URL`.

Stage 3 добавляет поиск пользователей, идемпотентное создание DM, cursor-history
и клиентские UUID сообщений. Контракты описаны в
[docs/stage-3-direct-messages.md](docs/stage-3-direct-messages.md).

## Миграции

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

Foundation revision сохраняет stage-0 чаты и сообщения. Legacy-участники без
учётной записи становятся неактивными placeholder users, чтобы все связи могли
иметь настоящие внешние ключи.

## Тесты

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm run build
```

# Secure Messenger

A FastAPI and React messenger backed by PostgreSQL and Redis.

> E2EE is not implemented yet. The server currently stores message content in
> plaintext. See [docs/README.md](docs/README.md) for the security specification.

## Quick start with Docker

Install Docker Desktop, open PowerShell in the repository root, and run:

```powershell
.\start.ps1
```

Alternatively, use Docker Compose directly:

```powershell
docker compose up --build
```

The services become available at:

- Web application: `http://localhost:8080`
- Backend API: `http://localhost:8000`
- OpenAPI documentation: `http://localhost:8000/docs`

The first startup builds both applications, waits for PostgreSQL and Redis, and
applies all Alembic migrations automatically. Later startups reuse the images
and persistent database volumes. Stop the stack with `Ctrl+C`.

To stop background containers:

```powershell
docker compose down
```

This command preserves database data. `docker compose down --volumes` deletes
the database and should only be used when that is intentional.

## Backend without Docker

For SQLite-based local development, run one command from the repository root:

```powershell
.\start-backend.ps1
```

The script:

1. creates `.venv` when needed;
2. checks that native Python dependencies can be imported;
3. moves a broken environment to `.venv.broken-<timestamp>` and recreates it;
4. installs dependencies;
5. applies Alembic migrations;
6. starts the API with auto-reload at `http://localhost:8000`.

The error `No module named 'pydantic_core._pydantic_core'` means the existing
virtual environment is incomplete or corrupted. The launcher repairs this
automatically without deleting the old environment.

Start the frontend in a second PowerShell window:

```powershell
cd frontend
npm install
npm run dev
```

The development frontend is available at `http://localhost:5173`.

## Manual backend commands

If you prefer to run each step yourself:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Run every command separately. Do not append the activation command to
`python -m app.main`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm run build
```

## Project layout

```text
app/                  FastAPI application
  routers/            auth, users, chats, messages, realtime
  services/           sessions, rate limiting, realtime delivery
migrations/           Alembic migrations
frontend/             React and Vite client
tests/                backend tests
compose.yaml          complete local application stack
```

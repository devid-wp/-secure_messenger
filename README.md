# Secure Messenger

A FastAPI and React messenger backed by PostgreSQL and Redis.

> E2EE is not implemented yet. The server currently stores message content in
> plaintext. See [docs/README.md](docs/README.md) for the security specification.

## Start without Docker

### Windows

Double-click `start.bat`. The launcher automatically:

- installs Python for the current user when it is missing;
- downloads a verified portable Node.js LTS when Node.js is missing;
- repairs an incomplete virtual environment;
- installs backend and frontend dependencies;
- applies database migrations;
- starts both servers and prints the application link.

You can also run it from Command Prompt:

```bat
start.bat
```

### Linux and macOS

Install Python 3.12+ and Node.js 20+, then run:

```sh
chmod +x start.sh
./start.sh
```

Both launchers use SQLite, so PostgreSQL, Redis, and Docker are not required.
Python and npm packages are installed only on the first run or when
`requirements*.txt`/`package-lock.json` changes. Alembic migrations still run
on every start because they are incremental and safe.

Open:

```text
http://localhost:5173
```

Keep the launcher terminal open. Press `Ctrl+C` to stop both servers. Startup
logs are stored in `.run` when troubleshooting is needed.

## Docker start

Install Docker Desktop, open PowerShell in the repository root, and run:

```powershell
.\start.ps1
```

You can also double-click `start-docker.bat`, or run it from Command Prompt:

```bat
start-docker.bat
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

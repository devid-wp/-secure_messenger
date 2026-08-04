# Secure Messenger

A FastAPI and React messenger backed by PostgreSQL and Redis.

> E2EE is not implemented yet. The server currently stores message content in
> plaintext. See [docs/README.md](docs/README.md) for the security specification.

Sticker packs and typed messages are available in the current pre-alpha build.
Encrypted attachment storage and S3-compatible transport are implemented on the
backend, but the browser attachment button intentionally remains disabled until
the MLS client can place the random file key inside a real E2EE envelope. See
[Stage 6 status](docs/stage-6-stickers-media.md).

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

## Windows desktop client

The Tauri desktop shell reuses the React interface and connects to the same
FastAPI service. It is an early native shell and does **not** provide E2EE yet.

Install these prerequisites first:

- Rust stable through rustup;
- Node.js 20 or newer;
- Microsoft Visual Studio 2022 Build Tools with **Desktop development with
  C++**, MSVC, and a Windows 10/11 SDK;
- Microsoft Edge WebView2 Evergreen Runtime.

Run the prerequisite diagnostics without starting anything:

```powershell
.\scripts\desktop-doctor.ps1
```

Start the desktop application from the repository root:

```powershell
.\start-desktop.bat
```

The launcher loads the MSVC developer environment, starts FastAPI when port
8000 is not already available, and then runs `tauri dev`. Desktop logs are
written under `.run`. The launcher stops only the backend process that it
started itself.

Verify the live desktop backend path, including registration, login, direct
chat creation, WebSocket delivery, acknowledgement, and message persistence:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-desktop-integration.ps1
```

After `npm run desktop:build`, verify the generated executable and NSIS bundle:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-desktop-artifacts.ps1
```

## Docker start

Install Docker Desktop, open PowerShell in the repository root, and run:

```powershell
.\start.ps1
```

For the fastest and most reproducible local start, double-click
`start-docker.bat`. The first run builds the images; later runs reuse them,
start in the background, wait for all health checks, and open the application
automatically.

```bat
start-docker.bat
```

Launcher maintenance commands:

```bat
start-docker.bat -Status
start-docker.bat -Logs
start-docker.bat -Stop
start-docker.bat -Rebuild
```

Alternatively, use Docker Compose directly:

```powershell
docker compose up --build
```

The services become available at:

- Web application: `http://localhost:8080`
- Backend API: `http://localhost:8000`
- OpenAPI documentation: `http://localhost:8000/docs`

The first startup builds both applications, waits for PostgreSQL, Redis, MinIO,
the API and frontend, and applies all Alembic migrations automatically. Later
startups reuse the images and persistent database volumes.

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

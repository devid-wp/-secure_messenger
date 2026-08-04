# Secure Messenger

FastAPI, React and Tauri messenger with a native OpenMLS cryptographic boundary.

## One-click Windows start

Double-click the only launcher in the repository root:

```text
start-docker.bat
```

It automatically:

1. checks for Docker Desktop;
2. installs the official Docker Desktop package when it is missing;
3. starts Docker and waits for its engine;
4. builds the application images on first launch;
5. starts PostgreSQL, Redis, MinIO, FastAPI and the frontend;
6. applies database migrations and waits for all health checks;
7. opens `http://localhost:8080`.

Docker Desktop installation can request administrator approval. Windows may
require one restart after enabling WSL 2; run `start-docker.bat` again after it.
If Windows reports component-store corruption `14098`, the launcher runs the
Microsoft-recommended DISM and SFC repair sequence before requesting a restart.

Useful commands:

```bat
start-docker.bat -Status
start-docker.bat -Logs
start-docker.bat -Stop
start-docker.bat -Rebuild
```

Persistent database and media volumes are preserved by `-Stop`. To remove them
intentionally, run `docker compose down --volumes` manually.

## Services

- Application: `http://localhost:8080`
- Backend API: `http://localhost:8000`
- OpenAPI: `http://localhost:8000/docs`
- MinIO console: `http://localhost:9001`

## Development

The Docker workflow is the supported local runtime. Individual components can
still be run directly with standard `uvicorn`, `npm`, `cargo`, Alembic and
pytest commands when developing them.

```powershell
docker compose up -d --wait
docker compose logs -f
python -m pytest
cd frontend
npm run lint
npm run build
```

Architecture and security documentation is under [docs](docs/README.md).

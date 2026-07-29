#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_ROOT"

VENV_PATH="$PROJECT_ROOT/.venv"
RUNTIME_PATH="$PROJECT_ROOT/.run"
FRONTEND_PATH="$PROJECT_ROOT/frontend"
mkdir -p "$RUNTIME_PATH"

if command -v python3 >/dev/null 2>&1; then
    SYSTEM_PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    SYSTEM_PYTHON=python
else
    echo "Python 3 is required."
    echo "Install Python 3.12 or newer and run ./start.sh again."
    exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "Node.js and npm are required."
    echo "Install Node.js 20 LTS or newer and run ./start.sh again."
    exit 1
fi

if [ ! -x "$VENV_PATH/bin/python" ]; then
    echo "Creating Python virtual environment..."
    "$SYSTEM_PYTHON" -m venv "$VENV_PATH"
fi

VENV_PYTHON="$VENV_PATH/bin/python"
if ! "$VENV_PYTHON" -c "import pydantic_core" >/dev/null 2>&1; then
    if [ -d "$VENV_PATH" ]; then
        BROKEN_PATH="$PROJECT_ROOT/.venv.broken-$(date +%Y%m%d-%H%M%S)"
        echo "Moving broken virtual environment to $BROKEN_PATH"
        mv "$VENV_PATH" "$BROKEN_PATH"
    fi
    echo "Creating clean Python virtual environment..."
    "$SYSTEM_PYTHON" -m venv "$VENV_PATH"
    rm -f "$RUNTIME_PATH/backend-dependencies.txt"
fi

hash_files() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$@" | sha256sum | cut -d ' ' -f 1
    else
        shasum -a 256 "$@" | shasum -a 256 | cut -d ' ' -f 1
    fi
}

BACKEND_FINGERPRINT=$(hash_files requirements.txt requirements-dev.txt)
BACKEND_MARKER="$RUNTIME_PATH/backend-dependencies.txt"
if [ ! -f "$BACKEND_MARKER" ] || [ "$(cat "$BACKEND_MARKER")" != "$BACKEND_FINGERPRINT" ]; then
    echo "Installing backend dependencies..."
    "$VENV_PYTHON" -m pip install --upgrade pip
    "$VENV_PYTHON" -m pip install -r requirements-dev.txt
    printf '%s\n' "$BACKEND_FINGERPRINT" > "$BACKEND_MARKER"
else
    echo "Backend dependencies are up to date."
fi

echo "Applying database migrations..."
"$VENV_PYTHON" -m alembic upgrade head

FRONTEND_FINGERPRINT=$(hash_files frontend/package-lock.json)
FRONTEND_MARKER="$RUNTIME_PATH/frontend-dependencies.txt"
if [ ! -d "$FRONTEND_PATH/node_modules" ] || [ ! -f "$FRONTEND_MARKER" ] || [ "$(cat "$FRONTEND_MARKER")" != "$FRONTEND_FINGERPRINT" ]; then
    echo "Installing frontend dependencies..."
    (cd "$FRONTEND_PATH" && npm install)
    printf '%s\n' "$FRONTEND_FINGERPRINT" > "$FRONTEND_MARKER"
else
    echo "Frontend dependencies are up to date."
fi

cleanup() {
    trap - INT TERM EXIT
    [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
    [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "Starting backend and frontend..."
"$VENV_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
    >"$RUNTIME_PATH/backend.log" 2>"$RUNTIME_PATH/backend-error.log" &
BACKEND_PID=$!
(cd "$FRONTEND_PATH" && npm run dev -- --host 127.0.0.1) \
    >"$RUNTIME_PATH/frontend.log" 2>"$RUNTIME_PATH/frontend-error.log" &
FRONTEND_PID=$!

wait_for_url() {
    URL=$1
    NAME=$2
    ATTEMPT=0
    while [ "$ATTEMPT" -lt 60 ]; do
        if "$VENV_PYTHON" -c "import urllib.request; urllib.request.urlopen('$URL', timeout=2)" >/dev/null 2>&1; then
            echo "$NAME is ready."
            return
        fi
        ATTEMPT=$((ATTEMPT + 1))
        sleep 1
    done
    echo "$NAME did not start. Check logs in $RUNTIME_PATH."
    exit 1
}

wait_for_url "http://127.0.0.1:8000/" "Backend"
wait_for_url "http://127.0.0.1:5173/" "Frontend"

echo ""
echo "Secure Messenger is ready:"
echo "http://localhost:5173"
echo ""
echo "Keep this terminal open. Press Ctrl+C to stop both servers."

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 1
done

echo "A server stopped unexpectedly. Check logs in $RUNTIME_PATH."
exit 1

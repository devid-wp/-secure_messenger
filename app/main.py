import sys
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, WebSocket, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import json

# Попытка импортировать C++ биндинги
try:
    build_path = Path(__file__).parent.parent / "core" / "build"
    if build_path.exists():
        sys.path.insert(0, str(build_path))
    import auth_core
    import crypto_core
    BINDINGS_AVAILABLE = True
except ImportError:
    BINDINGS_AVAILABLE = False
    print("⚠️ Внимание: C++ биндинги не найдены. Используется демо-режим.")

from database import Database

app = FastAPI(title="Secure Messenger API")

# CORS для localhost:5173 (Vite)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация БД
db = Database("secure_messenger.db")
db.create_tables()

# Хранилище активных токенов и соединений
active_tokens = {}  # {token: login}
active_connections = {}  # {token: WebSocket}


class RegisterRequest(BaseModel):
    login: str
    password: str


class LoginRequest(BaseModel):
    login: str
    password: str


class MessageRequest(BaseModel):
    to: str
    text: str


@app.post("/register")
async def register(req: RegisterRequest):
    """Регистрация нового пользователя"""
    if not req.login or not req.password:
        raise HTTPException(status_code=400, detail="Login and password are required")

    if db.user_exists(req.login):
        raise HTTPException(status_code=409, detail="User already exists")

    try:
        if BINDINGS_AVAILABLE:
            auth = auth_core.AuthManager()
            record = auth.register_user(req.login, req.password)
            hash_bytes = record["hash"]
            salt_bytes = record["salt"]
        else:
            # Демо-режим: используем простые значения
            hash_bytes = req.password.encode()
            salt_bytes = b"demo_salt_16byte"

        success = db.save_user(req.login, hash_bytes, salt_bytes)
        if not success:
            raise HTTPException(status_code=409, detail="User already exists")

        return {"status": "ok", "message": "User registered successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/login")
async def login(req: LoginRequest):
    """Вход пользователя и получение токена"""
    if not req.login or not req.password:
        raise HTTPException(status_code=400, detail="Login and password are required")

    user = db.get_user(req.login)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid login or password")

    try:
        if BINDINGS_AVAILABLE:
            auth = auth_core.AuthManager()
            is_valid = auth.verify_user(req.login, req.password, user["hash"], user["salt"])
        else:
            # Демо-режим: просто проверяем пароль
            is_valid = req.password.encode() == user["hash"]

        if not is_valid:
            raise HTTPException(status_code=401, detail="Invalid login or password")

        token = str(uuid4())
        active_tokens[token] = req.login

        return {"status": "ok", "token": token}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/messages")
async def get_messages(authorization: str = Header(None)):
    """Получить последние 50 сообщений пользователя"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization.replace("Bearer ", "")
    if token not in active_tokens:
        raise HTTPException(status_code=401, detail="Invalid token")

    login = active_tokens[token]
    messages = db.get_messages(login)

    return messages


@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """WebSocket для отправки и получения сообщений в реальном времени"""
    if token not in active_tokens:
        await websocket.close(code=4001, reason="Invalid token")
        return

    login = active_tokens[token]
    active_connections[token] = websocket

    try:
        await websocket.accept()

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            recipient = message.get("to")
            text = message.get("text")

            if not recipient or not text:
                continue

            # Сохраняем сообщение в БД
            db.save_message(login, recipient, text)

            # Если получатель онлайн, отправляем ему напрямую
            for conn_token, conn_websocket in list(active_connections.items()):
                if conn_token in active_tokens and active_tokens[conn_token] == recipient:
                    try:
                        await conn_websocket.send_text(json.dumps({
                            "from": login,
                            "text": text
                        }))
                    except:
                        pass

    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        active_connections.pop(token, None)


@app.get("/")
async def root():
    """Health check"""
    return {"status": "ok", "service": "Secure Messenger API"}


@app.on_event("shutdown")
async def shutdown():
    """Закрыть БД при завершении сервера"""
    db.close()


if __name__ == "__main__":
    print("🚀 Starting Secure Messenger API...")
    print(f"📦 C++ биндинги: {'✅ Available' if BINDINGS_AVAILABLE else '❌ Not available (Demo mode)'}")
    print("🌐 CORS enabled for localhost:5173 (Vite)")
    uvicorn.run(app, host="0.0.0.0", port=8000)

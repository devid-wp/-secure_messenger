import json
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from .auth import AuthError, register_user, verify_user
from .database import Database


app = FastAPI(title="Secure Messenger API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


db = Database("secure_messenger.db")
db.create_tables()

active_tokens: dict[str, str] = {}  # token -> login
active_connections: dict[str, WebSocket] = {}  # token -> ws


class Credentials(BaseModel):
    login: str
    password: str


class MessageRequest(BaseModel):
    to: str
    text: str


def _authenticate(authorization: str | None) -> str:
    """Проверить Bearer-токен и вернуть логин пользователя."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.removeprefix("Bearer ")
    login = active_tokens.get(token)
    if not login:
        raise HTTPException(status_code=401, detail="Invalid token")
    return login


@app.post("/register")
async def register(req: Credentials):
    """Регистрация нового пользователя."""
    if not req.login or not req.password:
        raise HTTPException(status_code=400, detail="Login and password are required")

    if db.user_exists(req.login):
        raise HTTPException(status_code=409, detail="User already exists")

    try:
        record = register_user(req.login, req.password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not db.save_user(record["login"], record["hash"], record["salt"]):
        raise HTTPException(status_code=409, detail="User already exists")

    return {"status": "ok", "message": "User registered successfully"}


@app.post("/login")
async def login(req: Credentials):
    """Вход пользователя и получение токена."""
    if not req.login or not req.password:
        raise HTTPException(status_code=400, detail="Login and password are required")

    user = db.get_user(req.login)
    if not user or not verify_user(req.login, req.password, user["hash"], user["salt"]):
        raise HTTPException(status_code=401, detail="Invalid login or password")

    token = str(uuid4())
    active_tokens[token] = req.login
    return {"status": "ok", "token": token}


@app.get("/messages")
async def get_messages(authorization: str | None = Header(None)):
    """Получить последние 50 сообщений пользователя."""
    login = _authenticate(authorization)
    return db.get_messages(login)


@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """WebSocket для обмена сообщениями в реальном времени."""
    login = active_tokens.get(token)
    if not login:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    active_connections[token] = websocket

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
                recipient = payload["to"]
                text = payload["text"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

            db.save_message(login, recipient, text)

            for other_token, other_login in list(active_tokens.items()):
                if other_login != recipient:
                    continue
                recipient_ws = active_connections.get(other_token)
                if recipient_ws is None:
                    continue
                try:
                    await recipient_ws.send_text(
                        json.dumps({"from": login, "text": text})
                    )
                except Exception:
                    # Получатель отвалился — вычистим его соединение.
                    active_connections.pop(other_token, None)
    except Exception as exc:
        print(f"WebSocket error: {exc}")
    finally:
        active_connections.pop(token, None)


@app.get("/")
async def root():
    """Health check."""
    return {"status": "ok", "service": "Secure Messenger API"}


@app.on_event("shutdown")
async def shutdown():
    db.close()


if __name__ == "__main__":
    print("🚀 Starting Secure Messenger API...")
    print("🌐 CORS enabled for localhost:5173 (Vite)")
    uvicorn.run(app, host="0.0.0.0", port=8000)

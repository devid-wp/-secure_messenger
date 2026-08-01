"""Live desktop API smoke test: authentication, DM creation, and WebSocket delivery."""

from __future__ import annotations

import argparse
import asyncio
import json
from urllib import error, request
from uuid import uuid4

import websockets


def api_request(base_url: str, method: str, path: str, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps(body).encode() if body is not None else None
    api_request = request.Request(
        f"{base_url}{path}", data=payload, headers=headers, method=method
    )
    try:
        with request.urlopen(api_request, timeout=10) as response:
            content = response.read()
            return json.loads(content) if content else None
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc


def register_and_login(base_url: str, login: str, password: str) -> str:
    api_request(
        base_url,
        "POST",
        "/api/v1/auth/register",
        {"login": login, "password": password, "device_name": "Desktop smoke test"},
    )
    session = api_request(
        base_url,
        "POST",
        "/api/v1/auth/login",
        {"login": login, "password": password, "device_name": "Desktop smoke test"},
    )
    token = session.get("token")
    if not token:
        raise RuntimeError("Login response did not contain a token.")
    return token


async def run_smoke(base_url: str) -> None:
    suffix = uuid4().hex[:10]
    alice_login = f"desktop_alice_{suffix}"
    bob_login = f"desktop_bob_{suffix}"
    password = f"Desktop-{uuid4().hex}"
    alice_token = register_and_login(base_url, alice_login, password)
    bob_token = register_and_login(base_url, bob_login, password)

    chat = api_request(
        base_url,
        "POST",
        "/api/v1/chats/dm",
        {"login": bob_login},
        alice_token,
    )
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
    client_id = str(uuid4())
    message_text = f"desktop-smoke-{suffix}"

    async with (
        websockets.connect(
            f"{ws_url}/api/v1/realtime/ws",
            subprotocols=[f"bearer.{alice_token}"],
            open_timeout=10,
        ) as alice_ws,
        websockets.connect(
            f"{ws_url}/api/v1/realtime/ws",
            subprotocols=[f"bearer.{bob_token}"],
            open_timeout=10,
        ) as bob_ws,
    ):
        await alice_ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "kind": "text",
                    "chat_id": chat["id"],
                    "content": message_text,
                    "client_id": client_id,
                    "reply_to_server_seq": None,
                    "sticker_id": None,
                    "attachment_id": None,
                    "key_envelope": None,
                }
            )
        )
        acknowledgement = json.loads(await asyncio.wait_for(alice_ws.recv(), 10))
        delivery = json.loads(await asyncio.wait_for(bob_ws.recv(), 10))

    if acknowledgement.get("type") != "message_ack":
        raise RuntimeError(f"Unexpected sender event: {acknowledgement}")
    if delivery.get("type") != "message" or delivery.get("content") != message_text:
        raise RuntimeError(f"Unexpected recipient event: {delivery}")
    if acknowledgement.get("id") != delivery.get("id"):
        raise RuntimeError("Sender acknowledgement and recipient delivery IDs differ.")

    history = api_request(
        base_url,
        "GET",
        f"/api/v1/chats/{chat['id']}/messages",
        token=alice_token,
    )
    if not any(item.get("content") == message_text for item in history["items"]):
        raise RuntimeError("Delivered message was not persisted in chat history.")

    print("Desktop integration smoke test passed:")
    print(f"  authentication: {alice_login}, {bob_login}")
    print(f"  chat: {chat['id']}")
    print(f"  WebSocket message: {acknowledgement['id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    asyncio.run(run_smoke(args.base_url.rstrip("/")))


if __name__ == "__main__":
    main()

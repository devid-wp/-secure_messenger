import json
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import Chat, ChatMember, Message, User
from app.services.serializers import serialize_message


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/realtime", tags=["realtime"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    protocols = websocket.headers.get("sec-websocket-protocol", "").split(",")
    bearer_protocol = next(
        (item.strip() for item in protocols if item.strip().startswith("bearer.")),
        None,
    )
    if bearer_protocol is None:
        await websocket.close(code=4001, reason="Missing token")
        return
    token = bearer_protocol.removeprefix("bearer.")
    session_store = websocket.app.state.session_store
    session_data = await session_store.resolve(token)
    if session_data is None:
        await websocket.close(code=4001, reason="Invalid token")
        return
    async with websocket.app.state.session_factory() as session:
        user = await session.get(User, session_data.user_id)
        if user is None or not user.is_active or user.is_placeholder:
            await websocket.close(code=4001, reason="Invalid token")
            return

    manager = websocket.app.state.connection_manager
    user_id = session_data.user_id
    await manager.connect(token, user_id, websocket, bearer_protocol)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
                chat_id = payload["chat_id"]
                text = payload["text"]
                raw_client_id = payload.get("client_id") or str(uuid4())
                if isinstance(chat_id, bool) or not isinstance(chat_id, int):
                    raise ValueError
                if not isinstance(text, str) or not text.strip():
                    raise ValueError
                client_id = str(UUID(raw_client_id))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                await websocket.send_json(
                    {"type": "error", "detail": "Invalid message payload"}
                )
                continue

            async with websocket.app.state.session_factory() as session:
                membership = await session.get(ChatMember, (chat_id, user_id))
                if membership is None:
                    await websocket.send_json(
                        {"type": "error", "detail": "Chat not found"}
                    )
                    continue
                message = await session.scalar(
                    select(Message)
                    .where(
                        Message.sender_user_id == user_id,
                        Message.client_id == client_id,
                    )
                    .options(selectinload(Message.sender))
                )
                if message is not None and (
                    message.chat_id != chat_id or message.content != text.strip()
                ):
                    await websocket.send_json(
                        {"type": "error", "detail": "client_id already used"}
                    )
                    continue
                is_new_message = message is None
                if message is None:
                    chat = await session.scalar(
                        select(Chat)
                        .where(Chat.id == chat_id)
                        .with_for_update()
                    )
                    if chat is None:
                        await websocket.send_json(
                            {"type": "error", "detail": "Chat not found"}
                        )
                        continue
                    server_seq = chat.next_message_seq
                    chat.next_message_seq += 1
                    message = Message(
                        chat_id=chat_id,
                        sender_user_id=user_id,
                        content=text.strip(),
                        client_id=client_id,
                        server_seq=server_seq,
                    )
                    session.add(message)
                    try:
                        await session.commit()
                    except IntegrityError:
                        await session.rollback()
                        is_new_message = False
                    message = await session.scalar(
                        select(Message)
                        .where(
                            Message.sender_user_id == user_id,
                            Message.client_id == client_id,
                        )
                        .options(selectinload(Message.sender))
                    )
                    if message is None or (
                        message.chat_id != chat_id
                        or message.content != text.strip()
                    ):
                        await websocket.send_json(
                            {"type": "error", "detail": "client_id already used"}
                        )
                        continue
                member_ids = set(
                    await session.scalars(
                        select(ChatMember.user_id).where(
                            ChatMember.chat_id == chat_id
                        )
                    )
                )
                serialized = serialize_message(message)
                serialized["timestamp"] = message.timestamp.isoformat()
            await manager.broadcast(
                member_ids if is_new_message else {user_id},
                {"type": "message", **serialized},
            )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected WebSocket error for user_id=%s", user_id)
    finally:
        await manager.disconnect(token)

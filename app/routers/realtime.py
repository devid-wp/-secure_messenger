import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import (
    Chat,
    ChatMember,
    MediaObject,
    Message,
    MessageReceipt,
    Sticker,
    StickerPackSubscription,
    User,
    UserBlock,
)
from app.services.serializers import serialize_message


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/realtime", tags=["realtime"])


def _message_options():
    return (
        selectinload(Message.sender),
        selectinload(Message.receipts),
        selectinload(Message.reply_to).selectinload(Message.sender),
        selectinload(Message.attachment),
        selectinload(Message.sticker).selectinload(Sticker.media),
    )


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
                event_type = payload.get("type", "send_message")
                if event_type in {"delivered", "read"}:
                    chat_id = payload["chat_id"]
                    server_seq = payload["server_seq"]
                    if (
                        isinstance(chat_id, bool)
                        or not isinstance(chat_id, int)
                        or isinstance(server_seq, bool)
                        or not isinstance(server_seq, int)
                    ):
                        raise ValueError
                    async with websocket.app.state.session_factory() as session:
                        membership = await session.get(
                            ChatMember,
                            (chat_id, user_id),
                        )
                        message = await session.scalar(
                            select(Message).where(
                                Message.chat_id == chat_id,
                                Message.server_seq == server_seq,
                            )
                        )
                        if (
                            membership is None
                            or message is None
                            or message.sender_user_id == user_id
                        ):
                            raise ValueError
                        receipt = await session.get(
                            MessageReceipt,
                            (message.id, user_id),
                        )
                        now = datetime.now(timezone.utc)
                        if receipt is None:
                            receipt = MessageReceipt(
                                message_id=message.id,
                                user_id=user_id,
                                status=event_type,
                                delivered_at=now,
                                read_at=now if event_type == "read" else None,
                            )
                            session.add(receipt)
                        elif event_type == "read":
                            receipt.status = "read"
                            receipt.read_at = receipt.read_at or now
                        await session.commit()
                        status_event = {
                            "type": "message_status",
                            "chat_id": chat_id,
                            "server_seq": server_seq,
                            "client_id": message.client_id,
                            "status": receipt.status,
                        }
                        sender_user_id = message.sender_user_id
                    await manager.broadcast({sender_user_id}, status_event)
                    continue
                if event_type != "send_message":
                    raise ValueError
                chat_id = payload["chat_id"]
                message_kind = payload.get("kind", "text")
                content = payload.get("content", payload.get("text", ""))
                attachment_id = payload.get("attachment_id")
                sticker_id = payload.get("sticker_id")
                key_envelope = payload.get("key_envelope")
                raw_client_id = payload.get("client_id") or str(uuid4())
                reply_to_server_seq = payload.get("reply_to_server_seq")
                if isinstance(chat_id, bool) or not isinstance(chat_id, int):
                    raise ValueError
                if message_kind not in {"text", "sticker", "image", "file"}:
                    raise ValueError
                if not isinstance(content, str):
                    raise ValueError
                content = content.strip()
                if message_kind == "text" and not (1 <= len(content) <= 16384):
                    raise ValueError
                if message_kind == "sticker":
                    if content or not isinstance(sticker_id, str):
                        raise ValueError
                    sticker_id = str(UUID(sticker_id))
                    if attachment_id is not None or key_envelope is not None:
                        raise ValueError
                elif message_kind in {"image", "file"}:
                    if len(content) > 4096 or not isinstance(attachment_id, str):
                        raise ValueError
                    attachment_id = str(UUID(attachment_id))
                    if (
                        not isinstance(key_envelope, str)
                        or not (1 <= len(key_envelope) <= 65536)
                    ):
                        raise ValueError
                    if sticker_id is not None:
                        raise ValueError
                elif attachment_id is not None or sticker_id is not None:
                    raise ValueError
                client_id = str(UUID(raw_client_id))
                if (
                    reply_to_server_seq is not None
                    and (
                        isinstance(reply_to_server_seq, bool)
                        or not isinstance(reply_to_server_seq, int)
                    )
                ):
                    raise ValueError
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
                chat_type = await session.scalar(
                    select(Chat.type).where(Chat.id == chat_id)
                )
                if chat_type == "dm":
                    other_member_ids = list(
                        await session.scalars(
                            select(ChatMember.user_id).where(
                                ChatMember.chat_id == chat_id,
                                ChatMember.user_id != user_id,
                            )
                        )
                    )
                    blocked = await session.scalar(
                        select(UserBlock).where(
                            or_(
                                and_(
                                    UserBlock.blocker_id == user_id,
                                    UserBlock.blocked_id.in_(other_member_ids),
                                ),
                                and_(
                                    UserBlock.blocked_id == user_id,
                                    UserBlock.blocker_id.in_(other_member_ids),
                                ),
                            )
                        )
                    )
                    if blocked is not None:
                        await websocket.send_json(
                            {"type": "error", "detail": "Messaging is blocked"}
                        )
                        continue
                message = await session.scalar(
                    select(Message)
                    .where(
                        Message.sender_user_id == user_id,
                        Message.client_id == client_id,
                    )
                    .options(*_message_options())
                )
                reply_to = None
                if reply_to_server_seq is not None:
                    reply_to = await session.scalar(
                        select(Message).where(
                            Message.chat_id == chat_id,
                            Message.server_seq == reply_to_server_seq,
                        )
                    )
                    if reply_to is None:
                        await websocket.send_json(
                            {"type": "error", "detail": "Reply target not found"}
                        )
                        continue
                sticker = None
                attachment = None
                if message_kind == "sticker":
                    sticker = await session.scalar(
                        select(Sticker)
                        .where(Sticker.id == sticker_id)
                        .options(
                            selectinload(Sticker.pack),
                            selectinload(Sticker.media),
                        )
                    )
                    if sticker is None:
                        await websocket.send_json(
                            {"type": "error", "detail": "Sticker not found"}
                        )
                        continue
                    subscribed = await session.get(
                        StickerPackSubscription,
                        (sticker.pack_id, user_id),
                    )
                    if (
                        sticker.pack.visibility != "public"
                        and sticker.pack.owner_user_id != user_id
                        and subscribed is None
                    ):
                        await websocket.send_json(
                            {"type": "error", "detail": "Sticker not found"}
                        )
                        continue
                elif message_kind in {"image", "file"}:
                    attachment = await session.get(MediaObject, attachment_id)
                    already_attached = await session.scalar(
                        select(Message.id).where(
                            Message.attachment_id == attachment_id,
                            Message.client_id != client_id,
                        )
                    )
                    if (
                        attachment is None
                        or attachment.owner_user_id != user_id
                        or attachment.purpose != "attachment"
                        or not attachment.is_encrypted
                        or already_attached is not None
                    ):
                        await websocket.send_json(
                            {
                                "type": "error",
                                "detail": "Encrypted attachment is unavailable",
                            }
                        )
                        continue
                if message is not None and (
                    message.chat_id != chat_id
                    or message.content != content
                    or message.kind != message_kind
                    or message.attachment_id != attachment_id
                    or message.sticker_id != sticker_id
                    or message.key_envelope != key_envelope
                    or message.reply_to_id != (
                        reply_to.id if reply_to is not None else None
                    )
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
                        content=content,
                        kind=message_kind,
                        attachment_id=attachment_id,
                        sticker_id=sticker_id,
                        key_envelope=key_envelope,
                        client_id=client_id,
                        server_seq=server_seq,
                        reply_to_id=reply_to.id if reply_to else None,
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
                        .options(*_message_options())
                    )
                    if message is None or (
                        message.chat_id != chat_id
                        or message.content != content
                        or message.kind != message_kind
                        or message.attachment_id != attachment_id
                        or message.sticker_id != sticker_id
                        or message.key_envelope != key_envelope
                        or message.reply_to_id != (
                            reply_to.id if reply_to is not None else None
                        )
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
            await websocket.send_json({"type": "message_ack", **serialized})
            if is_new_message:
                await manager.broadcast(
                    member_ids - {user_id},
                    {"type": "message", **serialized},
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected WebSocket error for user_id=%s", user_id)
    finally:
        await manager.disconnect(token)

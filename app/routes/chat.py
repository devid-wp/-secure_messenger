"""Chat, message, and user routes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..rate_limit import limiter
from ..auth import get_current_user
from ..db import get_session
from ..models import Chat, ChatMember, ChatType, MemberRole, Message, User
from ..realtime import hub
from ..schemas import (
    ChatCreateRequest,
    ChatMemberPublic,
    ChatPublic,
    MessageEditRequest,
    MessagePublic,
    MessageSendRequest,
    PublicKeyUpdate,
    UserPublic,
)
from ..services import (
    b64,
    b64_decode,
    create_group_chat,
    create_message,
    edit_message,
    get_chat_for_user,
    get_or_create_direct_chat,
    get_user_by_login,
    get_user_by_username,
    is_chat_member,
    list_chats_for_user,
    list_messages,
    mark_delivered,
    mark_read,
    search_users,
    serialize_chat_member,
    serialize_message,
    soft_delete_message,
    unread_count,
)

router = APIRouter(prefix="/api", tags=["chat"])


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@router.get("/users", response_model=List[UserPublic])
async def list_users(
    q: str = Query(default="", max_length=64),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if q:
        rows = await search_users(session, q, exclude_login=user.login)
    else:
        rows = await search_users(session, "", exclude_login=user.login, limit=200)
    out: list[dict] = []
    for row in rows:
        is_online = await hub.is_online(row.login)
        data = UserPublic.model_validate(row).model_dump(mode="json")
        data["is_online"] = is_online
        out.append(data)
    return out


@router.get("/users/{login}/pubkey", response_model=UserPublic)
async def get_user_pubkey(
    login: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    other = await get_user_by_login(session, login)
    if other is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic.model_validate(other)


@router.put("/users/me/pubkey", response_model=UserPublic)
async def update_my_pubkey(
    req: PublicKeyUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Publish or rotate the caller's public key.

    Accepts the raw key bytes as base64. We try to parse the candidate
    as an X25519 (32 B) or P-256 (65 B uncompressed / SPKI) public
    key — anything else is rejected so a corrupted or hostile key
    cannot break the recipient's decrypt.
    """
    try:
        key_bytes = b64_decode(req.public_key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid public_key encoding") from exc
    if not 16 <= len(key_bytes) <= 512:
        raise HTTPException(
            status_code=400,
            detail="public_key must be 16..512 bytes after base64 decode",
        )
    if not _is_well_formed_public_key(key_bytes):
        raise HTTPException(
            status_code=400,
            detail="Unsupported public key format (expected X25519 32B or P-256)",
        )
    user.public_key = key_bytes
    await session.commit()
    await session.refresh(user)
    return UserPublic.model_validate(user)


# ---------------------------------------------------------------------------
# Chats
# ---------------------------------------------------------------------------
@router.post("/chats", response_model=ChatPublic)
async def create_chat(
    req: ChatCreateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if req.direct_with:
        other = await get_user_by_login(session, req.direct_with) or await get_user_by_username(
            session, req.direct_with
        )
        if other is None:
            raise HTTPException(status_code=404, detail="User not found")
        if other.id == user.id:
            raise HTTPException(status_code=400, detail="Cannot chat with yourself")
        chat = await get_or_create_direct_chat(session, user=user, other=other)
    else:
        if not req.title or not req.member_logins:
            raise HTTPException(
                status_code=400, detail="Group chats need title and members"
            )
        members: list[User] = []
        for m in req.member_logins:
            target = await get_user_by_login(session, m) or await get_user_by_username(session, m)
            if target is None:
                raise HTTPException(status_code=404, detail=f"User {m} not found")
            if target.id == user.id:
                continue
            members.append(target)
        chat = await create_group_chat(session, owner=user, title=req.title, members=members)
    await session.commit()
    # Reload with members eagerly loaded to avoid lazy-load in async context.
    chat = (
        await session.execute(
            select(Chat)
            .where(Chat.id == chat.id)
            .options(selectinload(Chat.members).selectinload(ChatMember.user))
        )
    ).scalar_one()
    return await _chat_to_public(session, user, chat)


@router.get("/chats", response_model=List[ChatPublic])
async def list_my_chats(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    chats = await list_chats_for_user(session, user=user)
    return [await _chat_to_public(session, user, c) for c in chats]


@router.get("/chats/{chat_id}", response_model=ChatPublic)
async def get_chat(
    chat_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    chat = await get_chat_for_user(session, user=user, chat_id=chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _chat_to_public(session, user, chat)


@router.post("/chats/{chat_id}/read")
async def mark_chat_read(
    chat_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not await is_chat_member(session, user_id=user.id, chat_id=chat_id):
        raise HTTPException(status_code=403, detail="Not a member")
    n = await mark_read(session, user_id=user.id, chat_id=chat_id)
    await session.commit()
    await hub.publish(chat_id, {"type": "read", "chat_id": chat_id, "by": user.login})
    return {"marked": n}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
@router.get("/chats/{chat_id}/messages", response_model=List[MessagePublic])
async def list_chat_messages(
    chat_id: int,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not await is_chat_member(session, user_id=user.id, chat_id=chat_id):
        raise HTTPException(status_code=403, detail="Not a member")
    msgs = await list_messages(session, chat_id=chat_id, before_id=before_id, limit=limit)
    # Side-effect: stamp delivered when the receiver reads history.
    await mark_delivered(session, user_id=user.id, chat_id=chat_id)
    await session.commit()
    return [serialize_message(m) for m in msgs]


@router.post("/chats/{chat_id}/messages", response_model=MessagePublic, status_code=201)
@limiter.limit(get_settings().rate_limit_message)
async def send_message(
    request: Request,
    chat_id: int,
    req: MessageSendRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not await is_chat_member(session, user_id=user.id, chat_id=chat_id):
        raise HTTPException(status_code=403, detail="Not a member")

    ciphertext = b64_decode(req.ciphertext)
    nonce = b64_decode(req.nonce)
    if len(nonce) != 12:
        raise HTTPException(status_code=400, detail="nonce must be 12 bytes")

    msg = await create_message(
        session,
        chat_id=chat_id,
        sender_id=user.id,
        ciphertext=ciphertext,
        nonce=nonce,
        key_id=req.key_id,
        reply_to_id=req.reply_to_id,
    )
    await session.commit()
    payload = serialize_message(msg)
    await hub.publish(chat_id, {"type": "message", **payload})
    return payload


@router.patch("/messages/{message_id}", response_model=MessagePublic)
async def edit_my_message(
    message_id: int,
    req: MessageEditRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    msg = await edit_message(
        session,
        user=user,
        message_id=message_id,
        ciphertext=b64_decode(req.ciphertext),
        nonce=b64_decode(req.nonce),
    )
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not editable")
    await session.commit()
    payload = serialize_message(msg)
    await hub.publish(msg.chat_id, {"type": "edit", **payload})
    return payload


@router.delete("/messages/{message_id}", status_code=204)
async def delete_my_message(
    message_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    msg = (
        await session.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    ok = await soft_delete_message(session, user=user, message_id=message_id)
    if not ok:
        raise HTTPException(status_code=403, detail="Cannot delete")
    await session.commit()
    await hub.publish(msg.chat_id, {"type": "delete", "id": message_id, "chat_id": msg.chat_id})
    return None


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str,
    session: AsyncSession = Depends(get_session),
):
    """Token is passed as a query string. ``?token=...`` is the only auth."""
    from jose import JWTError, jwt

    from ..config import get_settings
    from ..auth import _decode  # re-use internal decoder

    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], issuer=settings.jwt_issuer
        )
    except JWTError:
        await websocket.close(code=4001)
        return

    if payload.get("typ") != "access":
        await websocket.close(code=4001)
        return

    login = payload.get("sub")
    user = (
        await session.execute(select(User).where(User.login == login))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    user.last_seen_at = datetime.now(tz=timezone.utc)
    await session.commit()

    chat_ids = (
        await session.execute(
            select(ChatMember.chat_id).where(ChatMember.user_id == user.id)
        )
    ).scalars().all()
    hub.attach(login=login, chat_ids=list(chat_ids), ws=websocket)
    await hub.mark_online(login)
    await hub.publish(0, {"type": "presence", "login": login, "online": True})

    try:
        while True:
            raw = await websocket.receive_text()
            import json as _json
            try:
                event = _json.loads(raw)
            except _json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "typing":
                chat_id = int(event.get("chat_id", 0))
                if chat_id:
                    await hub.publish(
                        chat_id,
                        {"type": "typing", "chat_id": chat_id, "from": login},
                    )
            elif kind == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.detach(websocket)
        await hub.mark_offline(login)
        await hub.publish(0, {"type": "presence", "login": login, "online": False})


# ---------------------------------------------------------------------------
# Compatibility shims
#
# The previous ``routes/compat.py`` exposed a plaintext-leaking variant
# of these endpoints. They are gone now, but the SPA still calls a few
# legacy URLs (``/api/search``, ``/api/messages``) for initial history
# loading. These shims return *only* the on-disk E2EE payload — no
# server-side decrypt is ever attempted.
# ---------------------------------------------------------------------------
@router.get("/search", response_model=List[UserPublic])
async def compat_search_users(
    q: str = Query(default="", max_length=64),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Alias of ``/api/users`` for the legacy search input."""
    rows = await search_users(session, q, exclude_login=user.login)
    out: list[dict] = []
    for row in rows:
        is_online = await hub.is_online(row.login)
        data = UserPublic.model_validate(row).model_dump(mode="json")
        data["is_online"] = is_online
        out.append(data)
    return out


@router.get("/messages")
async def compat_list_messages(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Return encrypted message history for every chat the user is in.

    The payload mirrors ``/api/chats/{chat_id}/messages`` but in a flat
    shape so the SPA's bulk-history loader keeps working. ``content`` is
    the base64 of the stored ciphertext — the client must decrypt it
    with the chat key it derives locally.
    """
    chat_ids = (
        await session.execute(
            select(ChatMember.chat_id).where(ChatMember.user_id == user.id)
        )
    ).scalars().all()
    if not chat_ids:
        return {"messages": []}

    stmt = (
        select(Message)
        .where(Message.chat_id.in_(chat_ids), Message.is_deleted.is_(False))
        .order_by(Message.created_at.asc())
        .options(selectinload(Message.sender))
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "messages": [
            {
                "id": m.id,
                "chat_id": m.chat_id,
                "sender": m.sender.login,
                "recipient": user.login,
                "content": b64(m.ciphertext),
                "nonce": b64(m.nonce),
                "timestamp": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ]
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_well_formed_public_key(key_bytes: bytes) -> bool:
    """Best-effort structural check for a freshly-uploaded public key.

    Tries X25519 (32 bytes), then P-256 uncompressed (65 B starting
    with 0x04) and finally generic DER/SPKI load. Any successful parse
    is considered a valid key for storage.
    """
    try:
        if len(key_bytes) == 32:
            X25519PublicKey.from_public_bytes(key_bytes)
            return True
        if len(key_bytes) == 65 and key_bytes[0] == 0x04:
            ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256R1(), key_bytes
            )
            return True
        # SPKI / DER / PEM fallback.
        serialization.load_der_public_key(key_bytes)
        return True
    except Exception:
        return False


async def _chat_to_public(session: AsyncSession, user: User, chat: Chat) -> dict:
    members = [serialize_chat_member(m) for m in chat.members]
    last = (
        await session.execute(
            select(Message)
            .where(Message.chat_id == chat.id)
            .options(
                selectinload(Message.attachments),
                selectinload(Message.sender),
            )
            .order_by(desc(Message.id))
            .limit(1)
        )
    ).scalars().first()
    unread = await unread_count(session, user_id=user.id, chat_id=chat.id)
    return {
        "id": chat.id,
        "type": chat.type.value if hasattr(chat.type, "value") else str(chat.type),
        "title": chat.title,
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
        "members": members,
        "last_message": serialize_message(last) if last else None,
        "unread_count": unread,
    }

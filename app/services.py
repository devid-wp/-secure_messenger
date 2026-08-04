"""Service layer: chat/membership/message queries.

Centralizing the queries keeps routers thin and makes it easier to swap
out the storage backend later. Functions here take an ``AsyncSession``
explicitly rather than using globals.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence

from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import (
    Attachment,
    Chat,
    ChatMember,
    ChatType,
    MemberRole,
    Message,
    User,
)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
async def get_user_by_login(session: AsyncSession, login: str) -> Optional[User]:
    return (
        await session.execute(select(User).where(User.login == login))
    ).scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    username = username.lstrip("@")
    return (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    login: str,
    username: str,
    email: str,
    password_hash: bytes,
    password_salt: bytes,
    public_key: bytes,
) -> User:
    user = User(
        login=login,
        username=username,
        email=email,
        password_hash=password_hash,
        password_salt=password_salt,
        public_key=public_key,
    )
    session.add(user)
    await session.flush()
    return user


async def search_users(
    session: AsyncSession,
    query: str,
    *,
    exclude_login: Optional[str] = None,
    limit: int = 20,
) -> List[User]:
    q = query.strip().lstrip("@")
    if not q:
        stmt = select(User)
        if exclude_login:
            stmt = stmt.where(User.login != exclude_login)
        stmt = stmt.order_by(User.username).limit(limit)
        return list((await session.execute(stmt)).scalars())

    # 1. Prefix search (case-insensitive where possible, uses index)
    stmt_prefix = select(User).where(
        or_(User.username.like(f"{q}%"), User.login.like(f"{q}%"))
    )
    if exclude_login:
        stmt_prefix = stmt_prefix.where(User.login != exclude_login)
    stmt_prefix = stmt_prefix.order_by(User.username).limit(limit)
    prefix_results = list((await session.execute(stmt_prefix)).scalars())

    if len(prefix_results) >= limit:
        return prefix_results

    # 2. Infix search for remaining slots
    exclude_ids = [u.id for u in prefix_results]
    stmt_infix = select(User).where(
        or_(User.username.ilike(f"%{q}%"), User.login.ilike(f"%{q}%"))
    )
    if exclude_ids:
        stmt_infix = stmt_infix.where(User.id.not_in(exclude_ids))
    if exclude_login:
        stmt_infix = stmt_infix.where(User.login != exclude_login)
    stmt_infix = stmt_infix.order_by(User.username).limit(limit - len(prefix_results))
    infix_results = list((await session.execute(stmt_infix)).scalars())

    return prefix_results + infix_results


# ---------------------------------------------------------------------------
# Chats
# ---------------------------------------------------------------------------
async def get_or_create_direct_chat(
    session: AsyncSession, *, user: User, other: User
) -> Chat:
    """Find an existing 1-on-1 chat between two users, or create one."""
    pair = and_(
        Chat.type == ChatType.direct,
        Chat.id.in_(
            select(ChatMember.chat_id).where(ChatMember.user_id == user.id)
        ),
        Chat.id.in_(
            select(ChatMember.chat_id).where(ChatMember.user_id == other.id)
        ),
    )
    existing = (await session.execute(select(Chat).where(pair))).scalars().first()
    if existing:
        return existing

    chat = Chat(type=ChatType.direct, title=None)
    session.add(chat)
    await session.flush()
    session.add_all(
        [
            ChatMember(chat_id=chat.id, user_id=user.id, role=MemberRole.owner),
            ChatMember(chat_id=chat.id, user_id=other.id, role=MemberRole.member),
        ]
    )
    await session.flush()
    return chat


async def create_group_chat(
    session: AsyncSession, *, owner: User, title: str, members: Iterable[User]
) -> Chat:
    chat = Chat(type=ChatType.group, title=title)
    session.add(chat)
    await session.flush()
    session.add(
        ChatMember(chat_id=chat.id, user_id=owner.id, role=MemberRole.owner)
    )
    for m in members:
        if m.id == owner.id:
            continue
        session.add(
            ChatMember(chat_id=chat.id, user_id=m.id, role=MemberRole.member)
        )
    await session.flush()
    return chat


async def list_chats_for_user(
    session: AsyncSession, *, user: User
) -> List[Chat]:
    stmt = (
        select(Chat)
        .join(ChatMember, ChatMember.chat_id == Chat.id)
        .where(ChatMember.user_id == user.id)
        .options(selectinload(Chat.members).selectinload(ChatMember.user))
        .order_by(desc(Chat.created_at))
    )
    return list((await session.execute(stmt)).scalars())


async def get_chat_for_user(
    session: AsyncSession, *, user: User, chat_id: int
) -> Optional[Chat]:
    stmt = (
        select(Chat)
        .join(ChatMember, ChatMember.chat_id == Chat.id)
        .where(ChatMember.user_id == user.id, Chat.id == chat_id)
        .options(selectinload(Chat.members).selectinload(ChatMember.user))
    )
    return (await session.execute(stmt)).scalars().first()


async def is_chat_member(
    session: AsyncSession, *, user_id: int, chat_id: int
) -> bool:
    return (
        await session.execute(
            select(ChatMember.id).where(
                ChatMember.user_id == user_id, ChatMember.chat_id == chat_id
            )
        )
    ).first() is not None


async def unread_count(
    session: AsyncSession, *, user_id: int, chat_id: int
) -> int:
    """Number of messages in this chat that the user has not yet read."""
    stmt = select(func.count(Message.id)).where(
        Message.chat_id == chat_id,
        Message.sender_id != user_id,
        Message.read_at.is_(None),
        Message.is_deleted.is_(False),
    )
    return int((await session.execute(stmt)).scalar_one())


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
async def create_message(
    session: AsyncSession,
    *,
    chat_id: int,
    sender_id: int,
    ciphertext: bytes,
    nonce: bytes,
    key_id: Optional[int] = None,
    reply_to_id: Optional[int] = None,
) -> Message:
    msg = Message(
        chat_id=chat_id,
        sender_id=sender_id,
        ciphertext=ciphertext,
        nonce=nonce,
        key_id=key_id,
        reply_to_id=reply_to_id,
    )
    session.add(msg)
    await session.flush()
    await session.refresh(msg, attribute_names=["sender", "attachments"])
    return msg


async def list_messages(
    session: AsyncSession,
    *,
    chat_id: int,
    before_id: Optional[int] = None,
    limit: int = 50,
) -> List[Message]:
    stmt = (
        select(Message)
        .where(Message.chat_id == chat_id)
        .options(
            selectinload(Message.attachments),
            selectinload(Message.sender),
        )
    )
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    stmt = stmt.order_by(desc(Message.id)).limit(limit)
    rows = list((await session.execute(stmt)).scalars())
    return list(reversed(rows))


async def mark_delivered(
    session: AsyncSession, *, user_id: int, chat_id: int
) -> int:
    """Stamp ``delivered_at`` on every message in the chat the user hasn't acked."""
    now = datetime.now(tz=timezone.utc)
    stmt = (
        update(Message)
        .where(
            Message.chat_id == chat_id,
            Message.sender_id != user_id,
            Message.delivered_at.is_(None),
            Message.is_deleted.is_(False),
        )
        .values(delivered_at=now)
        .returning(Message.id)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return len(rows)


async def mark_read(
    session: AsyncSession, *, user_id: int, chat_id: int
) -> int:
    now = datetime.now(tz=timezone.utc)
    stmt = (
        update(Message)
        .where(
            Message.chat_id == chat_id,
            Message.sender_id != user_id,
            Message.read_at.is_(None),
            Message.is_deleted.is_(False),
        )
        .values(delivered_at=now, read_at=now)
        .returning(Message.id)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return len(rows)


async def edit_message(
    session: AsyncSession, *, user: User, message_id: int, ciphertext: bytes, nonce: bytes
) -> Optional[Message]:
    msg = (
        await session.execute(
            select(Message).where(Message.id == message_id)
        )
    ).scalar_one_or_none()
    if msg is None or msg.sender_id != user.id or msg.is_deleted:
        return None
    msg.ciphertext = ciphertext
    msg.nonce = nonce
    msg.edited_at = datetime.now(tz=timezone.utc)
    await session.flush()
    await session.refresh(msg, attribute_names=["sender", "attachments"])
    return msg


async def soft_delete_message(
    session: AsyncSession, *, user: User, message_id: int
) -> bool:
    msg = (
        await session.execute(
            select(Message).where(Message.id == message_id)
        )
    ).scalar_one_or_none()
    if msg is None or msg.sender_id != user.id or msg.is_deleted:
        return False
    msg.is_deleted = True
    msg.ciphertext = b""
    msg.nonce = b""
    await session.flush()
    return True


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------
def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64_decode(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


def serialize_message(msg: Message) -> dict:
    return {
        "id": msg.id,
        "chat_id": msg.chat_id,
        "sender": msg.sender.login,
        "ciphertext": b64(msg.ciphertext),
        "nonce": b64(msg.nonce),
        "key_id": msg.key_id,
        "reply_to_id": msg.reply_to_id,
        "is_deleted": msg.is_deleted,
        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
        "delivered_at": msg.delivered_at.isoformat() if msg.delivered_at else None,
        "read_at": msg.read_at.isoformat() if msg.read_at else None,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "mime": a.mime,
                "size": a.size,
            }
            for a in (msg.attachments or [])
        ],
    }


def serialize_chat_member(m: ChatMember) -> dict:
    return {
        "login": m.user.login,
        "username": m.user.username,
        "role": m.role.value if hasattr(m.role, "value") else str(m.role),
        "public_key": b64(m.user.public_key) if m.user.public_key else None,
    }

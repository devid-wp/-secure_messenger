from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Chat, ChatMember, Message
from app.services.serializers import serialize_message


async def append_system_message(
    request: Request,
    session: AsyncSession,
    *,
    chat_id: int,
    actor_user_id: int,
    content: str,
) -> Message:
    chat = await session.scalar(
        select(Chat).where(Chat.id == chat_id).with_for_update()
    )
    if chat is None:
        raise RuntimeError("Chat disappeared while creating a system message")

    message = Message(
        chat_id=chat_id,
        sender_user_id=actor_user_id,
        content=content,
        kind="system",
        server_seq=chat.next_message_seq,
    )
    chat.next_message_seq += 1
    session.add(message)
    await session.commit()

    message = await session.scalar(
        select(Message)
        .where(Message.id == message.id)
        .options(
            selectinload(Message.sender),
            selectinload(Message.receipts),
            selectinload(Message.reply_to).selectinload(Message.sender),
        )
    )
    member_ids = set(
        await session.scalars(
            select(ChatMember.user_id).where(ChatMember.chat_id == chat_id)
        )
    )
    serialized = serialize_message(message)
    serialized["timestamp"] = message.timestamp.isoformat()
    await request.app.state.connection_manager.broadcast(
        member_ids,
        {"type": "message", **serialized},
    )
    return message

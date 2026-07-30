from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models import Chat, ChatMember, Message, Sticker, User
from app.schemas import MessageEditRequest, MessagePage, MessageResponse
from app.services.cursors import (
    InvalidCursor,
    decode_message_cursor,
    encode_message_cursor,
)
from app.services.serializers import serialize_message


router = APIRouter(prefix="/chats", tags=["messages"])


def _message_options():
    return (
        selectinload(Message.sender),
        selectinload(Message.receipts),
        selectinload(Message.reply_to).selectinload(Message.sender),
        selectinload(Message.attachment),
        selectinload(Message.sticker).selectinload(Sticker.media),
    )


@router.get("/{chat_id}/messages", response_model=MessagePage)
async def list_messages(
    chat_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=512),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    membership = await session.get(ChatMember, (chat_id, current_user.id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    before_id: int | None = None
    if cursor:
        try:
            before_id = decode_message_cursor(cursor, chat_id)
        except InvalidCursor as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    statement = select(Message).where(Message.chat_id == chat_id)
    chat = await session.get(Chat, chat_id)
    if (
        chat is not None
        and chat.type == "group"
        and chat.history_visibility == "since_join"
    ):
        statement = statement.where(
            Message.server_seq >= membership.history_from_seq
        )
    if before_id is not None:
        statement = statement.where(Message.id < before_id)
    rows = (
        await session.scalars(
            statement
            .options(*_message_options())
            .order_by(Message.id.desc())
            .limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = (
        encode_message_cursor(chat_id, page_rows[-1].id)
        if has_more and page_rows
        else None
    )
    return {
        "items": [
            serialize_message(message, current_user.id)
            for message in reversed(page_rows)
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


@router.patch(
    "/{chat_id}/messages/{server_seq}",
    response_model=MessageResponse,
)
async def edit_message(
    chat_id: int,
    server_seq: int,
    request_body: MessageEditRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    message = await session.scalar(
        select(Message)
        .where(
            Message.chat_id == chat_id,
            Message.server_seq == server_seq,
        )
        .options(*_message_options())
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.sender_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the sender can edit")
    if message.kind != "text":
        raise HTTPException(status_code=403, detail="Only text messages can be edited")
    if message.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Message is deleted")
    message.content = request_body.content.strip()
    if not message.content:
        raise HTTPException(status_code=400, detail="Message cannot be blank")
    message.edited_at = datetime.now(timezone.utc)
    await session.commit()
    message = await session.scalar(
        select(Message).where(Message.id == message.id).options(*_message_options())
    )
    serialized = serialize_message(message, current_user.id)
    serialized["timestamp"] = message.timestamp.isoformat()
    serialized["edited_at"] = message.edited_at.isoformat()
    member_ids = set(
        await session.scalars(
            select(ChatMember.user_id).where(ChatMember.chat_id == chat_id)
        )
    )
    await request.app.state.connection_manager.broadcast(
        member_ids,
        {"type": "message_updated", **serialized},
    )
    return serialized


@router.delete("/{chat_id}/messages/{server_seq}", status_code=204)
async def delete_message(
    chat_id: int,
    server_seq: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    message = await session.scalar(
        select(Message).where(
            Message.chat_id == chat_id,
            Message.server_seq == server_seq,
        )
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.sender_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the sender can delete")
    if message.kind == "system":
        raise HTTPException(status_code=403, detail="System messages cannot be deleted")
    if message.deleted_at is None:
        message.content = ""
        message.deleted_at = datetime.now(timezone.utc)
        await session.commit()
    member_ids = set(
        await session.scalars(
            select(ChatMember.user_id).where(ChatMember.chat_id == chat_id)
        )
    )
    await request.app.state.connection_manager.broadcast(
        member_ids,
        {
            "type": "message_deleted",
            "chat_id": chat_id,
            "server_seq": server_seq,
            "deleted_at": message.deleted_at.isoformat(),
        },
    )

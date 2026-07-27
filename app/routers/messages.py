from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models import ChatMember, Message, User
from app.schemas import MessagePage
from app.services.cursors import (
    InvalidCursor,
    decode_message_cursor,
    encode_message_cursor,
)
from app.services.serializers import serialize_message


router = APIRouter(prefix="/chats", tags=["messages"])


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
    if before_id is not None:
        statement = statement.where(Message.id < before_id)
    rows = (
        await session.scalars(
            statement
            .options(selectinload(Message.sender))
            .order_by(Message.timestamp.desc(), Message.id.desc())
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
            serialize_message(message) for message in reversed(page_rows)
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }

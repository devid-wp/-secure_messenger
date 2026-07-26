from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models import ChatMember, Message, User
from app.schemas import MessageResponse
from app.services.serializers import serialize_message


router = APIRouter(prefix="/chats", tags=["messages"])


@router.get("/{chat_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    chat_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    membership = await session.get(ChatMember, (chat_id, current_user.id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.chat_id == chat_id)
            .options(selectinload(Message.sender))
            .order_by(Message.timestamp.desc(), Message.id.desc())
            .limit(limit)
        )
    ).all()
    return [serialize_message(message) for message in reversed(rows)]

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models import Chat, ChatMember, User, UserBlock
from app.schemas import ChatResponse, DirectChatRequest
from app.services.serializers import serialize_chat


router = APIRouter(prefix="/chats", tags=["chats"])


def _chat_load_options():
    return (
        selectinload(Chat.creator),
        selectinload(Chat.members).selectinload(ChatMember.user),
    )


@router.get("", response_model=list[ChatResponse])
async def list_chats(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    chats = (
        await session.scalars(
            select(Chat)
            .join(ChatMember)
            .where(ChatMember.user_id == current_user.id)
            .options(*_chat_load_options())
            .order_by(Chat.created_at.desc(), Chat.id.desc())
        )
    ).all()
    return [serialize_chat(chat) for chat in chats]


@router.get("/dm", response_model=list[ChatResponse])
async def list_direct_chats(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    chats = (
        await session.scalars(
            select(Chat)
            .join(ChatMember)
            .where(
                ChatMember.user_id == current_user.id,
                Chat.type == "dm",
            )
            .options(*_chat_load_options())
            .order_by(Chat.created_at.desc(), Chat.id.desc())
        )
    ).all()
    return [serialize_chat(chat) for chat in chats]


@router.post("/dm", response_model=ChatResponse)
async def create_direct_chat(
    request_body: DirectChatRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    other_user = await session.scalar(
        select(User).where(
            User.login == request_body.login,
            User.is_active.is_(True),
            User.is_placeholder.is_(False),
        )
    )
    if other_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if other_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Invalid chat participant")
    block = await session.scalar(
        select(UserBlock).where(
            or_(
                and_(
                    UserBlock.blocker_id == current_user.id,
                    UserBlock.blocked_id == other_user.id,
                ),
                and_(
                    UserBlock.blocker_id == other_user.id,
                    UserBlock.blocked_id == current_user.id,
                ),
            )
        )
    )
    if block is not None:
        raise HTTPException(status_code=403, detail="Direct messages are blocked")

    direct_key = f"{min(current_user.id, other_user.id)}:{max(current_user.id, other_user.id)}"
    chat = await session.scalar(
        select(Chat)
        .where(Chat.direct_key == direct_key)
        .options(*_chat_load_options())
        .order_by(Chat.id)
    )
    if chat is None:
        chat = Chat(
            type="dm",
            name=None,
            direct_key=direct_key,
            created_by_user_id=current_user.id,
            members=[
                ChatMember(user_id=current_user.id, role="owner"),
                ChatMember(user_id=other_user.id, role="member"),
            ],
        )
        session.add(chat)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
        chat = await session.scalar(
            select(Chat)
            .where(Chat.direct_key == direct_key)
            .options(*_chat_load_options())
        )
    return serialize_chat(chat)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models import Chat, ChatMember, User, UserBlock
from app.schemas import (
    ChatResponse,
    DirectChatRequest,
    GroupCreateRequest,
    GroupMemberRequest,
    GroupUpdateRequest,
)
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


@router.get("/groups", response_model=list[ChatResponse])
async def list_groups(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    groups = (
        await session.scalars(
            select(Chat)
            .join(ChatMember)
            .where(
                ChatMember.user_id == current_user.id,
                Chat.type == "group",
            )
            .options(*_chat_load_options())
            .order_by(Chat.created_at.desc(), Chat.id.desc())
        )
    ).all()
    return [serialize_chat(group) for group in groups]


@router.post("/groups", response_model=ChatResponse, status_code=201)
async def create_group(
    request_body: GroupCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    name = request_body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name cannot be blank")
    requested_logins = {
        login.strip() for login in request_body.member_logins if login.strip()
    }
    requested_logins.discard(current_user.login)
    users = list(
        await session.scalars(
            select(User).where(
                User.login.in_(requested_logins),
                User.is_active.is_(True),
                User.is_placeholder.is_(False),
            )
        )
    )
    if len(users) != len(requested_logins):
        raise HTTPException(status_code=404, detail="One or more users not found")
    group = Chat(
        type="group",
        name=name,
        avatar_url=str(request_body.avatar_url) if request_body.avatar_url else None,
        created_by_user_id=current_user.id,
        members=[
            ChatMember(user_id=current_user.id, role="owner"),
            *(ChatMember(user_id=user.id, role="member") for user in users),
        ],
    )
    session.add(group)
    await session.commit()
    group = await session.scalar(
        select(Chat).where(Chat.id == group.id).options(*_chat_load_options())
    )
    return serialize_chat(group)


async def _group_and_actor(
    chat_id: int,
    actor_id: int,
    session: AsyncSession,
) -> tuple[Chat, ChatMember]:
    group = await session.scalar(
        select(Chat).where(Chat.id == chat_id, Chat.type == "group")
    )
    actor = await session.get(ChatMember, (chat_id, actor_id))
    if group is None or actor is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if actor.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return group, actor


@router.post("/groups/{chat_id}/members", response_model=ChatResponse)
async def add_group_member(
    chat_id: int,
    request_body: GroupMemberRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    _group, actor = await _group_and_actor(chat_id, current_user.id, session)
    if request_body.role == "admin" and actor.role != "owner":
        raise HTTPException(status_code=403, detail="Only owner can add admins")
    user = await session.scalar(
        select(User).where(
            User.login == request_body.login,
            User.is_active.is_(True),
            User.is_placeholder.is_(False),
        )
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    membership = await session.get(ChatMember, (chat_id, user.id))
    if membership is None:
        session.add(
            ChatMember(
                chat_id=chat_id,
                user_id=user.id,
                role=request_body.role,
            )
        )
    elif membership.role != request_body.role:
        if actor.role != "owner":
            raise HTTPException(status_code=403, detail="Only owner can change roles")
        membership.role = request_body.role
    await session.commit()
    group = await session.scalar(
        select(Chat).where(Chat.id == chat_id).options(*_chat_load_options())
    )
    return serialize_chat(group)


@router.delete("/groups/{chat_id}/members/{login}", status_code=204)
async def remove_group_member(
    chat_id: int,
    login: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    _group, actor = await _group_and_actor(chat_id, current_user.id, session)
    user = await session.scalar(select(User).where(User.login == login))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    membership = await session.get(ChatMember, (chat_id, user.id))
    if membership is None:
        return
    if membership.role == "owner":
        raise HTTPException(status_code=409, detail="Owner cannot be removed")
    if membership.role == "admin" and actor.role != "owner":
        raise HTTPException(status_code=403, detail="Only owner can remove admins")
    await session.delete(membership)
    await session.commit()


@router.patch("/groups/{chat_id}", response_model=ChatResponse)
async def update_group(
    chat_id: int,
    request_body: GroupUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    group = await session.scalar(
        select(Chat).where(Chat.id == chat_id, Chat.type == "group")
    )
    membership = await session.get(ChatMember, (chat_id, current_user.id))
    if group is None or membership is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if request_body.name is not None:
        group.name = request_body.name.strip()
        if not group.name:
            raise HTTPException(status_code=400, detail="Group name cannot be blank")
    if "avatar_url" in request_body.model_fields_set:
        group.avatar_url = (
            str(request_body.avatar_url) if request_body.avatar_url else None
        )
    await session.commit()
    group = await session.scalar(
        select(Chat).where(Chat.id == chat_id).options(*_chat_load_options())
    )
    return serialize_chat(group)

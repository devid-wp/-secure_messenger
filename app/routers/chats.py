from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models import Chat, ChatInvitation, ChatMember, User, UserBlock
from app.schemas import (
    ChatResponse,
    DirectChatRequest,
    GroupCreateRequest,
    GroupMemberRequest,
    GroupInvitationRequest,
    GroupInvitationResponse,
    GroupUpdateRequest,
)
from app.services.serializers import serialize_chat


router = APIRouter(prefix="/chats", tags=["chats"])


def _chat_load_options():
    return (
        selectinload(Chat.creator),
        selectinload(Chat.members).selectinload(ChatMember.user),
    )


def _serialize_invitation(invitation: ChatInvitation) -> dict:
    return {
        "id": invitation.id,
        "chat_id": invitation.chat_id,
        "group_name": invitation.chat.name,
        "inviter": invitation.inviter.login,
        "invitee": invitation.invitee.login,
        "status": invitation.status,
        "created_at": invitation.created_at,
        "expires_at": invitation.expires_at,
    }


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


@router.post(
    "/groups/{chat_id}/invitations",
    response_model=GroupInvitationResponse,
    status_code=201,
)
async def invite_group_member(
    chat_id: int,
    request_body: GroupInvitationRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    group, _actor = await _group_and_actor(chat_id, current_user.id, session)
    invitee = await session.scalar(
        select(User).where(
            User.login == request_body.login,
            User.is_active.is_(True),
            User.is_placeholder.is_(False),
        )
    )
    if invitee is None:
        raise HTTPException(status_code=404, detail="User not found")
    if await session.get(ChatMember, (chat_id, invitee.id)) is not None:
        raise HTTPException(status_code=409, detail="User is already a member")
    invitation = await session.scalar(
        select(ChatInvitation)
        .where(
            ChatInvitation.chat_id == chat_id,
            ChatInvitation.invitee_user_id == invitee.id,
            ChatInvitation.status == "pending",
        )
        .options(
            selectinload(ChatInvitation.chat),
            selectinload(ChatInvitation.inviter),
            selectinload(ChatInvitation.invitee),
        )
    )
    if invitation is None:
        invitation = ChatInvitation(
            id=str(uuid4()),
            chat_id=chat_id,
            inviter_user_id=current_user.id,
            invitee_user_id=invitee.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        session.add(invitation)
        await session.commit()
        invitation = await session.scalar(
            select(ChatInvitation)
            .where(ChatInvitation.id == invitation.id)
            .options(
                selectinload(ChatInvitation.chat),
                selectinload(ChatInvitation.inviter),
                selectinload(ChatInvitation.invitee),
            )
        )
    return _serialize_invitation(invitation)


@router.get(
    "/groups/invitations/pending",
    response_model=list[GroupInvitationResponse],
)
async def list_pending_invitations(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    invitations = list(
        await session.scalars(
            select(ChatInvitation)
            .where(
                ChatInvitation.invitee_user_id == current_user.id,
                ChatInvitation.status == "pending",
                ChatInvitation.expires_at > datetime.now(timezone.utc),
            )
            .options(
                selectinload(ChatInvitation.chat),
                selectinload(ChatInvitation.inviter),
                selectinload(ChatInvitation.invitee),
            )
            .order_by(ChatInvitation.created_at.desc())
        )
    )
    return [_serialize_invitation(item) for item in invitations]


@router.post(
    "/groups/invitations/{invitation_id}/accept",
    response_model=ChatResponse,
)
async def accept_group_invitation(
    invitation_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    invitation = await session.get(ChatInvitation, invitation_id)
    if invitation is None or invitation.invitee_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.status != "pending":
        raise HTTPException(status_code=409, detail="Invitation is not pending")
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Invitation expired")
    if await session.get(ChatMember, (invitation.chat_id, current_user.id)) is None:
        session.add(
            ChatMember(
                chat_id=invitation.chat_id,
                user_id=current_user.id,
                role="member",
            )
        )
    invitation.status = "accepted"
    await session.commit()
    group = await session.scalar(
        select(Chat)
        .where(Chat.id == invitation.chat_id)
        .options(*_chat_load_options())
    )
    return serialize_chat(group)


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

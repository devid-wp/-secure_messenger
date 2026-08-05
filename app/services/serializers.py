from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chat, MlsEnvelope


def serialize_chat(chat: Chat) -> dict:
    """Serialize routing metadata without client-visible group metadata."""
    return {
        "id": chat.id,
        "type": chat.type,
        "created_by": chat.creator.login,
        "created_at": chat.created_at,
        "members": sorted(member.user.login for member in chat.members),
        "member_roles": {
            member.user.login: member.role for member in chat.members
        },
        "avatar_url": chat.avatar_url,
        "history_visibility": chat.history_visibility,
    }


async def serialize_chat_summary(
    chat: Chat,
    viewer_user_id: int,
    session: AsyncSession,
) -> dict:
    """Return only membership/routing data; message state stays MLS-encrypted."""
    result = serialize_chat(chat)
    if chat.type == "dm":
        peer = next(
            (member.user for member in chat.members if member.user_id != viewer_user_id),
            None,
        )
        result["avatar_url"] = peer.avatar_url if peer is not None else None
        result["peer"] = (
            {
                "id": peer.id,
                "login": peer.login,
                "username": peer.username,
                "display_name": peer.display_name,
                "avatar_url": peer.avatar_url,
            }
            if peer is not None
            else None
        )
    result["last_envelope_id"] = await session.scalar(
        select(func.max(MlsEnvelope.id)).where(MlsEnvelope.chat_id == chat.id)
    )
    return result

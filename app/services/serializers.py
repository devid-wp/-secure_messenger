from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Chat, ChatMember, Message, MessageReceipt


def serialize_chat(chat: Chat) -> dict:
    return {
        "id": chat.id,
        "type": chat.type,
        "name": chat.name,
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
    """Serialize sidebar data without exposing message bodies outside membership."""
    membership = await session.get(ChatMember, (chat.id, viewer_user_id))
    history_from_seq = membership.history_from_seq if membership else 1
    latest = await session.scalar(
        select(Message)
        .where(
            Message.chat_id == chat.id,
            Message.server_seq >= history_from_seq,
        )
        .options(selectinload(Message.sender))
        .order_by(Message.server_seq.desc())
        .limit(1)
    )
    unread_count = await session.scalar(
        select(func.count(Message.id)).where(
            Message.chat_id == chat.id,
            Message.server_seq >= history_from_seq,
            Message.sender_user_id != viewer_user_id,
            ~exists().where(
                and_(
                    MessageReceipt.message_id == Message.id,
                    MessageReceipt.user_id == viewer_user_id,
                    MessageReceipt.status == "read",
                )
            ),
        )
    )
    result = serialize_chat(chat)
    if chat.type == "dm":
        peer = next(
            (
                member.user
                for member in chat.members
                if member.user_id != viewer_user_id
            ),
            None,
        )
        result["avatar_url"] = peer.avatar_url if peer is not None else None
    result["unread_count"] = unread_count or 0
    result["last_message"] = (
        {
            "sender": latest.sender.login,
            "kind": latest.kind,
            "content": latest.content,
            "timestamp": latest.timestamp,
        }
        if latest is not None
        else None
    )
    return result


def serialize_message(message: Message, viewer_user_id: int | None = None) -> dict:
    status = "sent"
    if viewer_user_id == message.sender_user_id:
        receipt_states = {receipt.status for receipt in message.receipts}
        if "read" in receipt_states:
            status = "read"
        elif "delivered" in receipt_states:
            status = "delivered"
    attachment = None
    if message.attachment is not None:
        attachment = {
            "id": message.attachment.id,
            "purpose": message.attachment.purpose,
            "content_type": message.attachment.content_type,
            "size_bytes": message.attachment.size_bytes,
            "sha256": message.attachment.sha256,
            "is_encrypted": message.attachment.is_encrypted,
            "cipher": message.attachment.cipher,
            "nonce": message.attachment.nonce,
            "width": message.attachment.width,
            "height": message.attachment.height,
            "content_url": f"/api/v1/media/{message.attachment.id}/content",
        }
    sticker = None
    if message.sticker is not None:
        sticker = {
            "id": message.sticker.id,
            "emoji": message.sticker.emoji,
            "position": message.sticker.position,
            "image_url": f"/api/v1/media/{message.sticker.media_object_id}/content",
            "width": message.sticker.media.width or 512,
            "height": message.sticker.media.height or 512,
        }
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "sender": message.sender.login,
        "content": message.content,
        "kind": message.kind,
        "client_id": message.client_id,
        "server_seq": message.server_seq,
        "status": status,
        "reply_to_server_seq": (
            message.reply_to.server_seq if message.reply_to else None
        ),
        "reply_to_sender": (
            message.reply_to.sender.login if message.reply_to else None
        ),
        "reply_to_content": (
            message.reply_to.content if message.reply_to else None
        ),
        "timestamp": message.timestamp,
        "edited_at": message.edited_at,
        "deleted_at": message.deleted_at,
        "attachment": attachment,
        "sticker": sticker,
        "key_envelope": message.key_envelope,
    }

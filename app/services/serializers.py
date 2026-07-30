from app.models import Chat, Message


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

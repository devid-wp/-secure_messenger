from app.models import Chat, Message


def serialize_chat(chat: Chat) -> dict:
    return {
        "id": chat.id,
        "type": chat.type,
        "name": chat.name,
        "created_by": chat.creator.login,
        "created_at": chat.created_at,
        "members": sorted(member.user.login for member in chat.members),
    }


def serialize_message(message: Message, viewer_user_id: int | None = None) -> dict:
    status = "sent"
    if viewer_user_id == message.sender_user_id:
        receipt_states = {receipt.status for receipt in message.receipts}
        if "read" in receipt_states:
            status = "read"
        elif "delivered" in receipt_states:
            status = "delivered"
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "sender": message.sender.login,
        "content": message.content,
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
    }

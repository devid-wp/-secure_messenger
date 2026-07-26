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


def serialize_message(message: Message) -> dict:
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "sender": message.sender.login,
        "content": message.content,
        "timestamp": message.timestamp,
    }

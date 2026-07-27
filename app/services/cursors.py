from __future__ import annotations

import base64
import json


class InvalidCursor(ValueError):
    pass


def encode_message_cursor(chat_id: int, before_id: int) -> str:
    payload = json.dumps(
        {"chat_id": chat_id, "before_id": before_id},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_message_cursor(cursor: str, expected_chat_id: int) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        chat_id = int(payload["chat_id"])
        before_id = int(payload["before_id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise InvalidCursor("Invalid cursor") from exc
    if chat_id != expected_chat_id or before_id < 1:
        raise InvalidCursor("Invalid cursor")
    return before_id

"""Attachment upload/download.

Files are stored encrypted at rest with the server's long-lived AES-GCM
key (see ``app.crypto``). Each upload produces an ``Attachment`` row
keyed to a specific message; the message body itself remains the E2EE
ciphertext produced by the client.
"""
from __future__ import annotations

import os
import secrets
import struct
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..crypto import Sealed, open_sealed, seal
from ..db import get_session
from ..models import Attachment, Message
from ..auth import get_current_user
from ..models import User
from ..services import is_chat_member

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


def _store_root() -> Path:
    settings = get_settings()
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _associated(chat_id: int, message_id: int) -> bytes:
    """AEAD ``associated`` context for an attachment.

    Binding the (chat_id, message_id) tuple into the AEAD tag domain
    prevents an attacker from swapping an attachment between messages
    or chats and having it still decrypt.
    """
    return struct.pack(">QI", chat_id, message_id)


@router.post("", status_code=201)
async def upload(
    message_id: int = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    if file.content_type not in settings.upload_allowed_mime:
        raise HTTPException(status_code=415, detail="Unsupported media type")

    msg = (
        await session.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id != user.id:
        raise HTTPException(status_code=403, detail="Not your message")
    if not await is_chat_member(session, user_id=user.id, chat_id=msg.chat_id):
        raise HTTPException(status_code=403, detail="Not a chat member")

    # Stream the upload so a 25 MB file doesn't get fully read into RAM.
    plaintext = bytearray()
    size = 0
    chunk_size = 64 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        size += len(chunk)
        if size > settings.upload_max_bytes:
            raise HTTPException(status_code=413, detail="File too large")
        plaintext.extend(chunk)

    sealed = seal(bytes(plaintext), associated=_associated(msg.chat_id, msg.id))
    fname = secrets.token_urlsafe(16)
    storage_path = _store_root() / fname
    storage_path.write_bytes(sealed.ciphertext)

    attachment = Attachment(
        message_id=msg.id,
        uploader_id=user.id,
        filename=file.filename or "file",
        mime=file.content_type or "application/octet-stream",
        size=len(plaintext),
        storage_path=str(storage_path),
        ciphertext_path=str(storage_path),
        nonce=sealed.nonce,
    )
    session.add(attachment)
    await session.commit()
    await session.refresh(attachment)
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "mime": attachment.mime,
        "size": attachment.size,
    }


@router.get("/{attachment_id}")
async def download(
    attachment_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    att = (
        await session.execute(
            select(Attachment).where(Attachment.id == attachment_id)
        )
    ).scalar_one_or_none()
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    msg = (
        await session.execute(select(Message).where(Message.id == att.message_id))
    ).scalar_one_or_none()
    if msg is None or not await is_chat_member(
        session, user_id=user.id, chat_id=msg.chat_id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")

    data = Path(att.ciphertext_path).read_bytes()
    plaintext = open_sealed(
        Sealed(ciphertext=data, nonce=att.nonce),
        associated=_associated(msg.chat_id, msg.id),
    )
    tmp_path = _store_root() / f"plain-{att.id}"
    tmp_path.write_bytes(plaintext)
    return FileResponse(
        path=str(tmp_path),
        media_type=att.mime,
        filename=att.filename,
        background=None,
    )

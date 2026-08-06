from __future__ import annotations

import hashlib
from io import BytesIO
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user, get_db
from app.models import (
    ChatMember,
    MediaObject,
    Sticker,
    StickerPack,
    StickerPackSubscription,
    User,
)
from app.schemas import (
    MediaObjectResponse,
    StickerPackCreate,
    StickerPackResponse,
    StickerPackUpdate,
    StickerResponse,
)


router = APIRouter(tags=["media"])
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_STICKER_SOURCE_BYTES = 5 * 1024 * 1024
STICKER_SIZE = 512
STICKER_TYPES = {"image/png", "image/webp"}


def _media_response(media: MediaObject) -> dict:
    return {
        "id": media.id,
        "purpose": media.purpose,
        "size_bytes": media.size_bytes,
        "sha256": media.sha256,
        "is_encrypted": media.is_encrypted,
        "content_url": f"/api/v1/media/{media.id}/content",
    }


def _sticker_response(sticker: Sticker) -> dict:
    return {
        "id": sticker.id,
        "emoji": sticker.emoji,
        "position": sticker.position,
        "image_url": f"/api/v1/media/{sticker.media_object_id}/content",
        "width": sticker.media.width or STICKER_SIZE,
        "height": sticker.media.height or STICKER_SIZE,
    }


def _pack_response(pack: StickerPack, current_user_id: int) -> dict:
    subscribed = any(
        subscription.user_id == current_user_id
        for subscription in pack.subscribers
    )
    return {
        "id": pack.id,
        "title": pack.title,
        "slug": pack.slug,
        "visibility": pack.visibility,
        "owner": pack.owner.login,
        "subscribed": subscribed,
        "editable": pack.owner_user_id == current_user_id,
        "stickers": [_sticker_response(sticker) for sticker in pack.stickers],
        "created_at": pack.created_at,
    }


def _pack_options():
    return (
        selectinload(StickerPack.owner),
        selectinload(StickerPack.subscribers),
        selectinload(StickerPack.stickers).selectinload(Sticker.media),
    )


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    content = await upload.read(limit + 1)
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded file is empty")
    if len(content) > limit:
        raise HTTPException(status_code=413, detail="The uploaded file is too large")
    return content


def _normalize_sticker(content: bytes, content_type: str) -> bytes:
    if content_type not in STICKER_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Stickers must be PNG or WebP images",
        )
    try:
        Image.MAX_IMAGE_PIXELS = 16_777_216
        with Image.open(BytesIO(content)) as source:
            source.load()
            if source.format not in {"PNG", "WEBP"}:
                raise HTTPException(status_code=415, detail="Invalid sticker image")
            converted = source.convert("RGBA")
            fitted = ImageOps.fit(
                converted,
                (STICKER_SIZE, STICKER_SIZE),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = BytesIO()
            fitted.save(output, format="WEBP", lossless=True, method=6)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=415, detail="Invalid sticker image") from exc


@router.post(
    "/media/attachments",
    response_model=MediaObjectResponse,
    status_code=201,
)
async def upload_encrypted_attachment(
    request: Request,
    ciphertext: UploadFile = File(),
    chat_id: int = Form(ge=1),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    submitted_fields = set((await request.form()).keys())
    forbidden_metadata = submitted_fields & {
        "name", "filename", "media_type", "plaintext_content_type", "key",
        "nonce", "cipher", "width", "height",
    }
    if forbidden_metadata:
        raise HTTPException(status_code=422, detail="Attachment metadata belongs inside the MLS ciphertext")
    if await session.get(ChatMember, (chat_id, current_user.id)) is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    content = await _read_limited(ciphertext, MAX_ATTACHMENT_BYTES)
    media_id = str(uuid4())
    object_key = f"attachments/{current_user.id}/{media_id}.bin"
    storage = request.app.state.object_storage
    await storage.put(object_key, content, "application/octet-stream")
    media = MediaObject(
        id=media_id,
        owner_user_id=current_user.id,
        chat_id=chat_id,
        purpose="attachment",
        object_key=object_key,
        storage_backend=storage.backend_name,
        content_type="application/octet-stream",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        is_encrypted=True,
    )
    session.add(media)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await storage.delete(object_key)
        raise
    return _media_response(media)


@router.get("/media/{media_id}/content")
async def download_media(
    media_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    media = await session.get(MediaObject, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media not found")
    allowed = media.owner_user_id == current_user.id
    if media.purpose == "attachment" and not allowed:
        allowed = media.chat_id is not None and await session.get(
            ChatMember, (media.chat_id, current_user.id)
        ) is not None
    if media.purpose == "sticker" and not allowed:
        allowed = bool(
            await session.scalar(
                select(
                    exists().where(
                        Sticker.media_object_id == media.id,
                        StickerPack.id == Sticker.pack_id,
                        or_(
                            StickerPack.visibility == "public",
                            exists().where(
                                StickerPackSubscription.pack_id == StickerPack.id,
                                StickerPackSubscription.user_id == current_user.id,
                            ),
                        ),
                    )
                )
            )
        )
    if not allowed:
        raise HTTPException(status_code=404, detail="Media not found")
    try:
        content = await request.app.state.object_storage.get(media.object_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Media object is missing") from exc
    return Response(
        content=content,
        media_type=(
            "application/octet-stream" if media.is_encrypted else media.content_type
        ),
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/sticker-packs",
    response_model=StickerPackResponse,
    status_code=201,
)
async def create_sticker_pack(
    request_body: StickerPackCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    pack = StickerPack(
        id=str(uuid4()),
        owner_user_id=current_user.id,
        title=request_body.title.strip(),
        slug=request_body.slug,
        visibility=request_body.visibility,
    )
    session.add(pack)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="You already have a sticker pack with this slug",
        ) from exc
    pack = await session.scalar(
        select(StickerPack).where(StickerPack.id == pack.id).options(*_pack_options())
    )
    return _pack_response(pack, current_user.id)


@router.get("/sticker-packs", response_model=list[StickerPackResponse])
async def list_sticker_packs(
    scope: str = Query(default="library", pattern=r"^(library|discover|owned)$"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    statement = select(StickerPack).options(*_pack_options())
    if scope == "discover":
        statement = statement.where(StickerPack.visibility == "public")
    elif scope == "owned":
        statement = statement.where(StickerPack.owner_user_id == current_user.id)
    else:
        statement = statement.where(
            or_(
                StickerPack.owner_user_id == current_user.id,
                exists().where(
                    StickerPackSubscription.pack_id == StickerPack.id,
                    StickerPackSubscription.user_id == current_user.id,
                ),
            )
        )
    packs = (await session.scalars(statement.order_by(StickerPack.created_at))).all()
    return [_pack_response(pack, current_user.id) for pack in packs]


@router.get(
    "/sticker-packs/{pack_id}",
    response_model=StickerPackResponse,
)
async def get_sticker_pack(
    pack_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    pack = await session.scalar(
        select(StickerPack)
        .where(StickerPack.id == pack_id)
        .options(*_pack_options())
    )
    if pack is None:
        raise HTTPException(status_code=404, detail="Sticker pack not found")
    subscribed = any(item.user_id == current_user.id for item in pack.subscribers)
    if (
        pack.visibility != "public"
        and pack.owner_user_id != current_user.id
        and not subscribed
    ):
        raise HTTPException(status_code=404, detail="Sticker pack not found")
    return _pack_response(pack, current_user.id)


@router.patch(
    "/sticker-packs/{pack_id}",
    response_model=StickerPackResponse,
)
async def update_sticker_pack(
    pack_id: str,
    request_body: StickerPackUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    pack = await session.get(StickerPack, pack_id)
    if pack is None or pack.owner_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Sticker pack not found")
    if request_body.title is not None:
        pack.title = request_body.title.strip()
    if request_body.visibility is not None:
        pack.visibility = request_body.visibility
    await session.commit()
    pack = await session.scalar(
        select(StickerPack).where(StickerPack.id == pack_id).options(*_pack_options())
    )
    return _pack_response(pack, current_user.id)


@router.post(
    "/sticker-packs/{pack_id}/stickers",
    response_model=StickerResponse,
    status_code=201,
)
async def add_sticker(
    pack_id: str,
    request: Request,
    sticker: UploadFile = File(),
    emoji: str | None = Form(default=None, max_length=32),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    pack = await session.get(StickerPack, pack_id)
    if pack is None or pack.owner_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Sticker pack not found")
    source = await _read_limited(sticker, MAX_STICKER_SOURCE_BYTES)
    normalized = _normalize_sticker(source, sticker.content_type or "")
    media_id = str(uuid4())
    sticker_id = str(uuid4())
    object_key = f"stickers/{current_user.id}/{media_id}.webp"
    storage = request.app.state.object_storage
    await storage.put(object_key, normalized, "image/webp")
    maximum_position = await session.scalar(
        select(func.max(Sticker.position)).where(Sticker.pack_id == pack_id)
    )
    position = 0 if maximum_position is None else maximum_position + 1
    media = MediaObject(
        id=media_id,
        owner_user_id=current_user.id,
        purpose="sticker",
        object_key=object_key,
        storage_backend=storage.backend_name,
        content_type="image/webp",
        size_bytes=len(normalized),
        sha256=hashlib.sha256(normalized).hexdigest(),
        is_encrypted=False,
        width=STICKER_SIZE,
        height=STICKER_SIZE,
    )
    sticker_record = Sticker(
        id=sticker_id,
        pack_id=pack_id,
        media=media,
        emoji=emoji.strip() if emoji else None,
        position=position,
    )
    session.add(sticker_record)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await storage.delete(object_key)
        raise
    sticker_record = await session.scalar(
        select(Sticker)
        .where(Sticker.id == sticker_id)
        .options(selectinload(Sticker.media))
    )
    return _sticker_response(sticker_record)


@router.post("/sticker-packs/{pack_id}/subscription", status_code=204)
async def subscribe_to_pack(
    pack_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    pack = await session.get(StickerPack, pack_id)
    if pack is None or pack.visibility != "public":
        raise HTTPException(status_code=404, detail="Sticker pack not found")
    if pack.owner_user_id == current_user.id:
        return Response(status_code=204)
    subscription = await session.get(
        StickerPackSubscription,
        (pack_id, current_user.id),
    )
    if subscription is None:
        session.add(
            StickerPackSubscription(pack_id=pack_id, user_id=current_user.id)
        )
        await session.commit()
    return Response(status_code=204)


@router.delete("/sticker-packs/{pack_id}/subscription", status_code=204)
async def unsubscribe_from_pack(
    pack_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    subscription = await session.get(
        StickerPackSubscription,
        (pack_id, current_user.id),
    )
    if subscription is not None:
        await session.delete(subscription)
        await session.commit()
    return Response(status_code=204)

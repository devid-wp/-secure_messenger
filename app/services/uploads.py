from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile


MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


def validate_avatar_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.startswith("/uploads/") or normalized.startswith(
        ("https://", "http://")
    ):
        return normalized
    raise HTTPException(status_code=422, detail="Invalid avatar URL")


async def save_image(upload: UploadFile, upload_dir: Path) -> str:
    extension = IMAGE_EXTENSIONS.get(upload.content_type or "")
    if extension is None:
        raise HTTPException(
            status_code=415,
            detail="Avatar must be a JPEG, PNG, or WebP image",
        )
    content = await upload.read(MAX_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Avatar must be between 1 byte and 5 MB",
        )
    signatures = IMAGE_SIGNATURES[upload.content_type]
    valid_signature = any(content.startswith(signature) for signature in signatures)
    if upload.content_type == "image/webp":
        valid_signature = valid_signature and content[8:12] == b"WEBP"
    if not valid_signature:
        raise HTTPException(status_code=415, detail="Invalid image content")
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{extension}"
    (upload_dir / filename).write_bytes(content)
    return f"/uploads/{filename}"

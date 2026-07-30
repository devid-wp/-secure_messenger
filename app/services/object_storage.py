from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from app.core.config import Settings


class ObjectStorage(Protocol):
    backend_name: str

    async def put(self, object_key: str, content: bytes, content_type: str) -> None: ...

    async def get(self, object_key: str) -> bytes: ...

    async def delete(self, object_key: str) -> None: ...


class LocalObjectStorage:
    backend_name = "local"

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        candidate = (self.root / object_key).resolve()
        if self.root not in candidate.parents:
            raise ValueError("Invalid object key")
        return candidate

    async def put(self, object_key: str, content: bytes, content_type: str) -> None:
        del content_type
        path = self._path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)

    async def get(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._path(object_key).read_bytes)

    async def delete(self, object_key: str) -> None:
        path = self._path(object_key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            pass


class S3ObjectStorage:
    backend_name = "s3"

    def __init__(self, settings: Settings):
        import boto3

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )

    async def put(self, object_key: str, content: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=object_key,
            Body=content,
            ContentType=content_type,
        )

    async def get(self, object_key: str) -> bytes:
        response = await asyncio.to_thread(
            self.client.get_object,
            Bucket=self.bucket,
            Key=object_key,
        )
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(
            self.client.delete_object,
            Bucket=self.bucket,
            Key=object_key,
        )


def create_object_storage(settings: Settings) -> ObjectStorage:
    if settings.media_storage_backend == "s3":
        return S3ObjectStorage(settings)
    return LocalObjectStorage(settings.media_dir)

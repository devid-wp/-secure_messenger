from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Device, User


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    request: Request,
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.removeprefix("Bearer ")
    session_data = await request.app.state.session_store.resolve(token)
    if session_data is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    await request.app.state.rate_limiter.check(f"api:device:{session_data.device_id}")
    device = await session.get(Device, session_data.device_id)
    user = await session.get(User, session_data.user_id)
    if device is not None and device.status == "pending" and device.revoked_at is None:
        raise HTTPException(status_code=403, detail="Device approval required")
    if device is None or device.revoked_at is not None or device.status != "active":
        await request.app.state.session_store.revoke(token)
        raise HTTPException(status_code=401, detail="Invalid token")
    if user is None or not user.is_active or user.is_placeholder:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user


async def get_bearer_token(authorization: str | None = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return authorization.removeprefix("Bearer ")


async def get_current_device(
    request: Request,
    token: str = Depends(get_bearer_token),
    session: AsyncSession = Depends(get_db),
) -> Device:
    session_data = await request.app.state.session_store.resolve(token)
    if session_data is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    await request.app.state.rate_limiter.check(f"api:device:{session_data.device_id}")
    device = await session.get(Device, session_data.device_id)
    user = await session.get(User, session_data.user_id)
    if (
        device is None
        or device.revoked_at is not None
        or device.status == "revoked"
        or user is None
        or not user.is_active
        or user.is_placeholder
    ):
        await request.app.state.session_store.revoke(token)
        raise HTTPException(status_code=401, detail="Invalid token")
    return device


async def get_active_device(
    request: Request,
    token: str = Depends(get_bearer_token),
    session: AsyncSession = Depends(get_db),
) -> Device:
    device = await get_current_device(request, token, session)
    if device.status != "active":
        raise HTTPException(status_code=403, detail="Device approval required")
    return device

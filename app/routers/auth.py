from datetime import datetime, timezone
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthError, register_user, verify_password
from app.dependencies import get_bearer_token, get_current_user, get_db
from app.models import Device, User
from app.schemas import Credentials, DeviceResponse, TokenResponse


router = APIRouter(prefix="/auth", tags=["auth"])


async def _available_username(login: str, session: AsyncSession) -> str:
    base = re.sub(r"[^a-z0-9_]", "_", login.lower()).strip("_")
    if len(base) < 3:
        base = f"user_{base}"
    base = base[:32]

    candidate = base
    suffix = 1
    while await session.scalar(select(User.id).where(User.username == candidate)):
        ending = f"_{suffix}"
        candidate = f"{base[: 32 - len(ending)]}{ending}"
        suffix += 1
    return candidate


@router.post("/register", status_code=201)
async def register(
    request_body: Credentials,
    session: AsyncSession = Depends(get_db),
):
    existing = await session.scalar(
        select(User).where(User.login == request_body.login)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="User already exists")
    try:
        record = register_user(request_body.login, request_body.password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = User(
        login=record["login"],
        username=await _available_username(record["login"], session),
        password_hash=record["hash"].encode(),
        password_salt=b"",
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="User already exists") from exc
    return {"status": "ok", "message": "User registered successfully"}


@router.post("/login", response_model=TokenResponse)
async def login(
    request_body: Credentials,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    client_host = request.client.host if request.client else "unknown"
    await request.app.state.rate_limiter.check(
        f"login:{client_host}:{request_body.login.strip().lower()}",
        limit=10,
    )
    user = await session.scalar(
        select(User).where(
            User.login == request_body.login,
            User.is_active.is_(True),
            User.is_placeholder.is_(False),
        )
    )
    valid, replacement_hash = (
        verify_password(request_body.password, user.password_hash, user.password_salt)
        if user is not None
        else (False, None)
    )
    if user is None or not valid:
        raise HTTPException(status_code=401, detail="Invalid login or password")
    if replacement_hash:
        user.password_hash = replacement_hash.encode()
        user.password_salt = b""
    device = Device(
        id=str(uuid4()),
        user_id=user.id,
        name=request_body.device_name.strip(),
    )
    session.add(device)
    await session.commit()
    token = await request.app.state.session_store.issue(user.id, device.id)
    return TokenResponse(token=token, device_id=device.id)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    token: str = Depends(get_bearer_token),
    _user: User = Depends(get_current_user),
):
    await request.app.state.session_store.revoke(token)


@router.get("/devices", response_model=list[DeviceResponse])
async def devices(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return list(
        await session.scalars(
            select(Device)
            .where(Device.user_id == current_user.id)
            .order_by(Device.created_at.desc())
        )
    )


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(
    device_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    device = await session.get(Device, device_id)
    if device is None or device.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.revoked_at is None:
        device.revoked_at = datetime.now(timezone.utc)
        await session.commit()
    await request.app.state.session_store.revoke_device(device_id)

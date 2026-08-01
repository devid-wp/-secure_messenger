from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthError, register_user, verify_password
from app.dependencies import get_bearer_token, get_current_device, get_db
from app.models import ChatMember, Device, RefreshSession, SecurityEvent, User
from app.schemas import Credentials, DeviceResponse, RefreshRequest, TokenResponse


router = APIRouter(prefix="/auth", tags=["auth"])
MAX_ACTIVE_DEVICES = 5
REFRESH_COOKIE = "refresh_token"


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _set_refresh_cookie(response: Response, token: str, request: Request) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_ttl_seconds,
        httponly=True,
        secure=settings.environment not in {"development", "test"},
        samesite="lax",
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        httponly=True,
        secure=request.app.state.settings.environment not in {"development", "test"},
        samesite="lax",
        path="/api/v1/auth",
    )


async def _issue_tokens(
    *, user: User, device: Device, request: Request, response: Response,
    session: AsyncSession, client_type: str, refresh_session: RefreshSession | None = None,
) -> TokenResponse:
    refresh_token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    if refresh_session is None:
        refresh_session = RefreshSession(
            id=str(uuid4()), user_id=user.id, device_id=device.id,
            device_name=device.name,
            refresh_token_hash=_hash_refresh_token(refresh_token),
            expires_at=now + timedelta(seconds=request.app.state.settings.refresh_ttl_seconds),
        )
        session.add(refresh_session)
    else:
        refresh_session.refresh_token_hash = _hash_refresh_token(refresh_token)
    await session.commit()
    access_token = await request.app.state.session_store.issue(user.id, device.id)
    if client_type == "web":
        _set_refresh_cookie(response, refresh_token, request)
    return TokenResponse(
        token=access_token,
        access_token=access_token,
        refresh_token=refresh_token if client_type == "desktop" else None,
        expires_in=request.app.state.settings.session_ttl_seconds,
        login=user.login,
        device_id=device.id,
        device_status=device.status,
    )


def _device_response(device: Device, current_device_id: str) -> dict:
    return {
        "id": device.id,
        "name": device.name,
        "created_at": device.created_at,
        "last_seen_at": device.last_seen_at,
        "revoked_at": device.revoked_at,
        "status": device.status,
        "current": device.id == current_device_id,
        "fingerprint": device.identity_fingerprint,
        "approved_by_device_id": device.approved_by_device_id,
        "approved_at": device.approved_at,
        "pairing_expires_at": device.pairing_expires_at,
        "history_policy": device.history_policy,
    }


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
    response: Response,
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
        ).with_for_update()
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
    now = datetime.now(timezone.utc)
    device_count = await session.scalar(select(func.count(Device.id)).where(
        Device.user_id == user.id,
        Device.status == "active",
        Device.revoked_at.is_(None),
    ))
    if (device_count or 0) >= MAX_ACTIVE_DEVICES:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Device limit reached (maximum 5)")
    device_id = str(uuid4())
    device = Device(
        id=device_id,
        user_id=user.id,
        name=request_body.device_name.strip(),
        status="active",
        approved_at=now,
    )
    session.add(device)
    return await _issue_tokens(
        user=user, device=device, request=request, response=response,
        session=session, client_type=request_body.client_type,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    request_body: RefreshRequest | None = None,
    session: AsyncSession = Depends(get_db),
):
    client_type = request_body.client_type if request_body else "web"
    raw_token = (
        request_body.refresh_token if request_body and request_body.refresh_token
        else request.cookies.get(REFRESH_COOKIE)
    )
    if not raw_token:
        raise HTTPException(status_code=401, detail="Refresh token required")
    record = await session.scalar(
        select(RefreshSession)
        .where(RefreshSession.refresh_token_hash == _hash_refresh_token(raw_token))
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    expires_at = record.expires_at if record is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if record is None or record.revoked_at is not None or expires_at <= now:
        _clear_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    device = await session.get(Device, record.device_id)
    user = await session.get(User, record.user_id)
    if (
        device is None or device.revoked_at is not None or device.status != "active"
        or user is None or not user.is_active or user.is_placeholder
    ):
        record.revoked_at = now
        await session.commit()
        _clear_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    device.last_seen_at = now
    return await _issue_tokens(
        user=user, device=device, request=request, response=response,
        session=session, client_type=client_type, refresh_session=record,
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    request_body: RefreshRequest | None = None,
    token: str = Depends(get_bearer_token),
    session: AsyncSession = Depends(get_db),
):
    await request.app.state.session_store.revoke(token)
    raw_refresh = (
        request_body.refresh_token if request_body and request_body.refresh_token
        else request.cookies.get(REFRESH_COOKIE)
    )
    if raw_refresh:
        record = await session.scalar(select(RefreshSession).where(
            RefreshSession.refresh_token_hash == _hash_refresh_token(raw_refresh)
        ))
        if record is not None and record.revoked_at is None:
            record.revoked_at = datetime.now(timezone.utc)
            await session.commit()
    _clear_refresh_cookie(response, request)


@router.get("/devices", response_model=list[DeviceResponse])
async def devices(
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
):
    rows = list(
        await session.scalars(
            select(Device)
            .where(Device.user_id == current_device.user_id)
            .order_by(Device.created_at.desc())
        )
    )
    return [_device_response(device, current_device.id) for device in rows]


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(
    device_id: str,
    request: Request,
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
):
    device = await session.get(Device, device_id)
    if device is None or device.user_id != current_device.user_id:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.revoked_at is None:
        device.revoked_at = datetime.now(timezone.utc)
        device.status = "revoked"
        await session.commit()
    await session.execute(
        RefreshSession.__table__.update()
        .where(RefreshSession.device_id == device_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await session.commit()
    await request.app.state.session_store.revoke_device(device_id)
    await request.app.state.connection_manager.close_device(device_id)
    await request.app.state.connection_manager.broadcast(
        {current_device.user_id},
        {
            "type": "security_event",
            "event": "device_revoked",
            "device_id": device.id,
            "device_name": device.name,
            "fingerprint": device.identity_fingerprint,
            "mls_action": "remove_commit_required",
        },
    )
    chat_ids = select(ChatMember.chat_id).where(
        ChatMember.user_id == current_device.user_id
    )
    contact_ids = set(await session.scalars(
        select(ChatMember.user_id).where(
            ChatMember.chat_id.in_(chat_ids),
            ChatMember.user_id != current_device.user_id,
        )
    ))
    session.add_all([
        SecurityEvent(
            id=str(uuid4()),
            recipient_user_id=contact_id,
            event_type="fingerprint_changed",
            subject_user_id=current_device.user_id,
            device_id=device.id,
            fingerprint=device.identity_fingerprint,
        )
        for contact_id in contact_ids
    ])
    await session.commit()
    await request.app.state.connection_manager.broadcast(
        contact_ids,
        {
            "type": "security_event",
            "event": "fingerprint_changed",
            "user_id": current_device.user_id,
            "reason": "device_revoked",
            "fingerprint": device.identity_fingerprint,
        },
    )

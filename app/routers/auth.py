from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthError, register_user, verify_password
from app.dependencies import get_bearer_token, get_current_device, get_db
from app.models import ChatMember, Device, SecurityEvent, User
from app.schemas import Credentials, DeviceApprovalRequest, DeviceResponse, TokenResponse


router = APIRouter(prefix="/auth", tags=["auth"])
MAX_ACTIVE_DEVICES = 5


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
    stale_pending = list(await session.scalars(select(Device).where(
        Device.user_id == user.id,
        Device.status == "pending",
        Device.pairing_expires_at < now,
    )))
    for stale in stale_pending:
        stale.status = "revoked"
        stale.revoked_at = now
    device_count = await session.scalar(select(func.count(Device.id)).where(
        Device.user_id == user.id,
        Device.status.in_(("active", "pending")),
    ))
    if (device_count or 0) >= MAX_ACTIVE_DEVICES:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Device limit reached (maximum 5)")
    active_count = await session.scalar(select(func.count(Device.id)).where(
        Device.user_id == user.id,
        Device.status == "active",
        Device.revoked_at.is_(None),
    ))
    status = "active" if not active_count else "pending"
    pairing_code = secrets.token_urlsafe(24) if status == "pending" else None
    device_id = str(uuid4())
    device = Device(
        id=device_id,
        user_id=user.id,
        name=request_body.device_name.strip(),
        status=status,
        approved_at=now if status == "active" else None,
        pairing_code_hash=sha256(pairing_code.encode()).hexdigest() if pairing_code else None,
        pairing_expires_at=now + timedelta(minutes=10) if pairing_code else None,
    )
    session.add(device)
    await session.commit()
    token = await request.app.state.session_store.issue(user.id, device.id)
    return TokenResponse(
        token=token,
        device_id=device.id,
        device_status=status,
        pairing_code=pairing_code,
        pairing_uri=(f"secure-messenger://pair?device={device.id}&code={pairing_code}" if pairing_code else None),
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    token: str = Depends(get_bearer_token),
    _device: Device = Depends(get_current_device),
):
    await request.app.state.session_store.revoke(token)


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


@router.post("/devices/{device_id}/approve", response_model=DeviceResponse)
async def approve_device(
    device_id: str,
    request_body: DeviceApprovalRequest,
    request: Request,
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
):
    if current_device.status != "active":
        raise HTTPException(status_code=403, detail="A trusted device must approve this request")
    target = await session.get(Device, device_id)
    if target is None or target.user_id != current_device.user_id:
        raise HTTPException(status_code=404, detail="Device not found")
    if target.status != "pending" or target.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Device is not awaiting approval")
    now = datetime.now(timezone.utc)
    supplied_hash = sha256(request_body.pairing_code.encode()).hexdigest()
    pairing_expires_at = target.pairing_expires_at
    if pairing_expires_at is not None and pairing_expires_at.tzinfo is None:
        pairing_expires_at = pairing_expires_at.replace(tzinfo=timezone.utc)
    if pairing_expires_at is None or pairing_expires_at < now:
        raise HTTPException(status_code=410, detail="Pairing request expired")
    if not secrets.compare_digest(target.pairing_code_hash or "", supplied_hash):
        raise HTTPException(status_code=403, detail="Invalid pairing code")
    target.status = "active"
    target.approved_by_device_id = current_device.id
    target.approved_at = now
    target.history_policy = request_body.history_policy
    target.pairing_code_hash = None
    await session.commit()
    await session.refresh(target)
    await request.app.state.connection_manager.broadcast(
        {current_device.user_id},
        {
            "type": "security_event",
            "event": "device_approved",
            "device_id": target.id,
            "device_name": target.name,
            "history_policy": target.history_policy,
            "mls_action": "add_commit_required",
        },
    )
    return _device_response(target, current_device.id)


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

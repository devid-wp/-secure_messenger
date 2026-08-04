import base64
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_active_device, get_db
from app.models import ChatMember, Device, MlsKeyPackage, SecurityEvent, User
from app.schemas import (
    DeviceIdentityPublish,
    DeviceIdentityResponse,
    KeyPackagePublish,
    KeyPackageInventory,
    KeyPackageResponse,
    SecurityEventResponse,
)


router = APIRouter(prefix="/e2ee", tags=["e2ee"])
MLS_CIPHER_SUITE = 1


def _identity_response(device: Device) -> dict:
    return {
        "device_id": device.id,
        "login": device.user.login,
        "identity_key": base64.b64encode(device.identity_key),
        "fingerprint": device.identity_fingerprint,
        "published_at": device.identity_published_at,
    }


@router.put("/identity", response_model=DeviceIdentityResponse)
async def publish_identity(
    request_body: DeviceIdentityPublish,
    request: Request,
    current_device: Device = Depends(get_active_device),
    session: AsyncSession = Depends(get_db),
):
    identity_key = bytes(request_body.identity_key)
    fingerprint = sha256(identity_key).hexdigest()
    if current_device.identity_key is not None:
        if current_device.identity_key != identity_key:
            raise HTTPException(
                status_code=409,
                detail="Device identity is immutable; create a new device",
            )
    else:
        collision = await session.scalar(
            select(Device.id).where(
                Device.identity_fingerprint == fingerprint,
                Device.id != current_device.id,
            )
        )
        if collision is not None:
            raise HTTPException(status_code=409, detail="Identity key already in use")
        current_device.identity_key = identity_key
        current_device.identity_fingerprint = fingerprint
        current_device.identity_published_at = datetime.now(timezone.utc)
        await session.commit()
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
                device_id=current_device.id,
                fingerprint=fingerprint,
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
                "device_id": current_device.id,
                "fingerprint": fingerprint,
            },
        )
    current_device = await session.scalar(
        select(Device)
        .where(Device.id == current_device.id)
        .options(selectinload(Device.user))
    )
    return _identity_response(current_device)


@router.get("/security-events", response_model=list[SecurityEventResponse])
async def list_security_events(
    current_device: Device = Depends(get_active_device),
    session: AsyncSession = Depends(get_db),
):
    return list(await session.scalars(
        select(SecurityEvent).where(
            SecurityEvent.recipient_user_id == current_device.user_id,
            SecurityEvent.acknowledged_at.is_(None),
        ).order_by(SecurityEvent.created_at.desc()).limit(50)
    ))


@router.post("/security-events/{event_id}/acknowledge", status_code=204)
async def acknowledge_security_event(
    event_id: str,
    current_device: Device = Depends(get_active_device),
    session: AsyncSession = Depends(get_db),
):
    event = await session.get(SecurityEvent, event_id)
    if event is None or event.recipient_user_id != current_device.user_id:
        raise HTTPException(status_code=404, detail="Security event not found")
    if event.acknowledged_at is None:
        event.acknowledged_at = datetime.now(timezone.utc)
        await session.commit()


@router.get(
    "/users/{login}/identities",
    response_model=list[DeviceIdentityResponse],
)
async def list_user_identities(
    login: str,
    _current_device: Device = Depends(get_active_device),
    session: AsyncSession = Depends(get_db),
):
    devices = list(
        await session.scalars(
            select(Device)
            .join(User)
            .where(
                User.login == login,
                User.is_active.is_(True),
                Device.revoked_at.is_(None),
                Device.identity_key.is_not(None),
            )
            .options(selectinload(Device.user))
            .order_by(Device.created_at, Device.id)
        )
    )
    if not devices:
        raise HTTPException(status_code=404, detail="No E2EE devices found")
    return [_identity_response(device) for device in devices]


@router.post("/key-packages", status_code=201)
async def publish_key_packages(
    request_body: KeyPackagePublish,
    current_device: Device = Depends(get_active_device),
    session: AsyncSession = Depends(get_db),
):
    if current_device.identity_key is None:
        raise HTTPException(status_code=409, detail="Publish device identity first")
    if request_body.cipher_suite != MLS_CIPHER_SUITE:
        raise HTTPException(status_code=422, detail="Unsupported MLS ciphersuite")
    expires_at = request_body.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="KeyPackages must expire in future")
    packages = [bytes(item) for item in request_body.key_packages]
    if any(not 64 <= len(item) <= 65_536 for item in packages):
        raise HTTPException(status_code=422, detail="Invalid KeyPackage size")
    for package in packages:
        session.add(
            MlsKeyPackage(
                id=str(uuid4()),
                device_id=current_device.id,
                key_package=package,
                cipher_suite=request_body.cipher_suite,
                expires_at=expires_at,
            )
        )
    await session.commit()
    return {"published": len(packages)}


@router.get("/key-packages/status", response_model=KeyPackageInventory)
async def key_package_inventory(
    current_device: Device = Depends(get_active_device),
    session: AsyncSession = Depends(get_db),
):
    available = await session.scalar(
        select(func.count(MlsKeyPackage.id)).where(
            MlsKeyPackage.device_id == current_device.id,
            MlsKeyPackage.claimed_at.is_(None),
            MlsKeyPackage.expires_at > datetime.now(timezone.utc),
            MlsKeyPackage.cipher_suite == MLS_CIPHER_SUITE,
        )
    )
    return {"available": available or 0, "cipher_suite": MLS_CIPHER_SUITE}


@router.post(
    "/users/{login}/key-packages/claim",
    response_model=list[KeyPackageResponse],
)
async def claim_key_packages(
    login: str,
    current_device: Device = Depends(get_active_device),
    session: AsyncSession = Depends(get_db),
):
    target_devices = list(
        await session.scalars(
            select(Device)
            .join(User)
            .where(
                User.login == login,
                User.is_active.is_(True),
                Device.revoked_at.is_(None),
                Device.identity_key.is_not(None),
            )
            .order_by(Device.created_at, Device.id)
        )
    )
    now = datetime.now(timezone.utc)
    claimed: list[MlsKeyPackage] = []
    for device in target_devices:
        package = await session.scalar(
            select(MlsKeyPackage)
            .where(
                MlsKeyPackage.device_id == device.id,
                MlsKeyPackage.claimed_at.is_(None),
                MlsKeyPackage.expires_at > now,
            )
            .order_by(MlsKeyPackage.created_at, MlsKeyPackage.id)
            .with_for_update(skip_locked=True)
        )
        if package is not None:
            package.claimed_at = now
            package.claimed_by_device_id = current_device.id
            claimed.append(package)
    await session.commit()
    return [
        {
            "id": package.id,
            "device_id": package.device_id,
            "key_package": base64.b64encode(package.key_package),
            "cipher_suite": package.cipher_suite,
            "expires_at": package.expires_at,
        }
        for package in claimed
    ]

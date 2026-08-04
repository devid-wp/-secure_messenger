"""Authentication routes: register, login, refresh, logout, 2FA setup."""
from __future__ import annotations

import base64
import io

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (
    generate_salt,
    get_current_user,
    get_current_user_from_refresh,
    hash_password,
    issue_token_pair,
    revoke_all_refresh,
    revoke_refresh,
    verify_password,
)
from ..config import get_settings
from ..db import get_session
from ..models import User
from ..rate_limit import limiter
from ..schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    TwoFactorConfirmRequest,
    TwoFactorSetupResponse,
    UserPublic,
)
from ..services import b64_decode, create_user, get_user_by_login
from ..twofa import store as pending_2fa

router = APIRouter(tags=["auth"])


@router.post("/register")
@limiter.limit("20/hour")
async def register(
    request: Request,
    req: RegisterRequest,
    session: AsyncSession = Depends(get_session),
):
    """Register a new user with their X25519 public key."""
    settings = get_settings()

    if await get_user_by_login(session, req.login):
        raise HTTPException(status_code=409, detail="Login already taken")

    existing = (
        await session.execute(
            select(User).where(
                (User.username == req.username) | (User.email == req.email)
            )
        )
    ).scalars().first()
    if existing:
        if existing.username == req.username:
            raise HTTPException(status_code=409, detail="Username already taken")
        raise HTTPException(status_code=409, detail="Email already taken")

    if req.public_key:
        try:
            public_key = b64_decode(req.public_key)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid public_key") from exc
        if len(public_key) != 32:
            raise HTTPException(status_code=400, detail="public_key must be 32 bytes")
    else:
        public_key = b'\x00' * 32

    salt = generate_salt()
    pw_hash = hash_password(req.password, salt)
    user = await create_user(
        session,
        login=req.login,
        username=req.username,
        email=req.email,
        password_hash=pw_hash,
        password_salt=salt,
        public_key=public_key,
    )
    await session.commit()
    return {"status": "ok", "user_id": user.id}


@router.post("/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    req: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    user = await get_user_by_login(session, req.login)
    if user is None or not verify_password(
        req.password, user.password_salt, user.password_hash
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.totp_enabled:
        if not req.totp_code:
            raise HTTPException(status_code=401, detail="2FA code required")
        if not user.totp_secret:
            raise HTTPException(status_code=500, detail="2FA misconfigured")
        if not pyotp.TOTP(user.totp_secret).verify(req.totp_code, valid_window=1):
            raise HTTPException(status_code=401, detail="Invalid 2FA code")

    access, refresh, _, refresh_ttl = await issue_token_pair(login=user.login)
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=refresh_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/api/auth",
    )
    return {
        "status": "ok",
        "access_token": access,
        "token": access,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl_seconds,
        "user": UserPublic.model_validate(user).model_dump(mode="json"),
    }


@router.post("/refresh")
async def refresh(
    response: Response,
    session: AsyncSession = Depends(get_session),
    payload: tuple[User, str, str] = Depends(get_current_user_from_refresh),
):
    user, login, jti = payload
    await revoke_refresh(login, jti)
    access, refresh, _, refresh_ttl = await issue_token_pair(login=login)
    settings = get_settings()
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=refresh_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/api/auth",
    )
    return {
        "access_token": access,
        "token": access,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl_seconds,
    }


@router.post("/logout")
async def logout(
    response: Response,
    user: User = Depends(get_current_user),
):
    response.delete_cookie("refresh_token", path="/api/auth")
    await revoke_all_refresh(user.login)
    return {"status": "ok"}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"status": "ok", "user": UserPublic.model_validate(user).model_dump(mode="json")}


# ---------------------------------------------------------------------------
# 2FA
# ---------------------------------------------------------------------------
@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA already enabled")

    # Generate the secret and stash it ONLY in the in-memory pending
    # store. We do not write it to the database until the user proves
    # control by submitting a valid code on /2fa/enable — otherwise a
    # secret left behind by an abandoned setup could be brute-forced.
    secret = pyotp.random_base32()
    await pending_2fa.put(user.id, secret)
    # Invalidate any leftover secret on the user row from a previous
    # failed/aborted flow.
    if user.totp_secret:
        user.totp_secret = None
        await session.commit()

    issuer = get_settings().project_name
    otpauth = pyotp.TOTP(secret).provisioning_uri(
        name=user.login, issuer_name=issuer
    )
    img = qrcode.make(otpauth)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return TwoFactorSetupResponse(secret=secret, otpauth_url=otpauth, qr_png_base64=qr_b64)


@router.post("/2fa/enable")
async def enable_2fa(
    req: TwoFactorConfirmRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA already enabled")

    # Pull the pending secret from the in-memory store. It is removed
    # atomically (one-shot) so a second enable attempt with the same
    # code is impossible.
    secret = await pending_2fa.take(user.id)
    if secret is None:
        raise HTTPException(
            status_code=400,
            detail="2FA setup not started or expired; restart setup",
        )
    if not pyotp.TOTP(secret).verify(req.code, valid_window=1):
        # Re-arm so the user can retry without re-scanning the QR.
        await pending_2fa.put(user.id, secret)
        raise HTTPException(status_code=400, detail="Invalid code")
    user.totp_secret = secret
    user.totp_enabled = True
    await session.commit()
    return {"status": "ok"}


@router.post("/2fa/disable")
async def disable_2fa(
    req: TwoFactorConfirmRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA not enabled")
    if not pyotp.TOTP(user.totp_secret).verify(req.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid code")
    user.totp_enabled = False
    user.totp_secret = None
    await session.commit()
    return {"status": "ok"}

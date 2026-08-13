from datetime import datetime
from typing import Literal

from pydantic import Base64Bytes, BaseModel as PydanticBaseModel, ConfigDict, Field


class BaseModel(PydanticBaseModel):
    """Fail closed on fields not declared by the API contract."""

    model_config = ConfigDict(extra="forbid")


class Credentials(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    device_name: str = Field(default="Web browser", min_length=1, max_length=128)
    client_type: Literal["web", "desktop"] = "web"


class TokenResponse(BaseModel):
    status: str = "ok"
    token: str
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int
    login: str
    device_id: str
    device_status: str = "active"


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=32, max_length=512)
    client_type: Literal["web", "desktop"] = "web"


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None
    status: str
    current: bool = False
    fingerprint: str | None = None
    approved_by_device_id: str | None = None
    approved_at: datetime | None = None
    pairing_expires_at: datetime | None = None
    history_policy: str


class SecurityEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    subject_user_id: int
    device_id: str | None
    fingerprint: str | None
    created_at: datetime


class DeviceIdentityPublish(BaseModel):
    identity_key: Base64Bytes = Field(min_length=32, max_length=128)


class DeviceIdentityResponse(BaseModel):
    device_id: str
    login: str
    identity_key: Base64Bytes
    fingerprint: str
    published_at: datetime


class KeyPackagePublish(BaseModel):
    key_packages: list[Base64Bytes] = Field(min_length=1, max_length=100)
    cipher_suite: int = Field(default=1, ge=1, le=65535)
    expires_at: datetime


class KeyPackageResponse(BaseModel):
    id: str
    device_id: str
    key_package: Base64Bytes
    cipher_suite: int
    expires_at: datetime


class KeyPackageInventory(BaseModel):
    available: int
    cipher_suite: int


class MlsEnvelopePublish(BaseModel):
    # Wire-level envelope around an opaque MLS ciphertext. The server MUST NOT
    # parse `payload` or store any field derived from its plaintext. Only
    # routing metadata is allowed here: protocol version, chat, epoch, content
    # kind, the ciphertext itself, and the optional welcome recipient.
    # `extra="forbid"` rejects any field that could leak message text, sender
    # name, file name, MIME type, reply preview, group name, reaction or edit
    # information.
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = 1
    epoch: int = Field(ge=0)
    content_type: Literal["application", "commit", "proposal", "welcome"]
    payload: Base64Bytes = Field(min_length=1, max_length=1_048_576)
    recipient_device_id: str | None = Field(default=None, max_length=36)


class MlsEnvelopeResponse(BaseModel):
    # Read-only mirror of MlsEnvelopePublish plus server-side routing fields.
    # Mirrors the same forbidden-fields policy: chat_id, sender_device_id and
    # created_at are routing metadata only and never carry plaintext.
    id: int
    chat_id: int
    sender_device_id: str
    recipient_device_id: str | None
    protocol_version: int
    epoch: int
    content_type: str
    payload: Base64Bytes
    created_at: datetime


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    username: str
    display_name: str | None
    bio: str | None
    avatar_url: str | None
    created_at: datetime


class ProfileUpdateRequest(BaseModel):
    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=32,
        pattern=r"^[a-z0-9][a-z0-9_]{2,31}$",
    )
    display_name: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=160)


class DirectChatRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)


class ChatPeer(BaseModel):
    id: int
    login: str
    username: str
    display_name: str | None
    avatar_url: str | None


class ChatResponse(BaseModel):
    id: int
    type: str
    created_by: str
    created_at: datetime
    members: list[str]
    member_roles: dict[str, str]
    avatar_url: str | None
    history_visibility: str
    peer: ChatPeer | None = None
    last_envelope_id: int | None = None


class GroupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avatar_url: str | None = Field(default=None, max_length=2048)
    member_logins: list[str] = Field(default_factory=list, max_length=99)
    history_visibility: str = Field(
        default="since_join",
        pattern="^(all|since_join)$",
    )


class GroupUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avatar_url: str | None = Field(default=None, max_length=2048)
    history_visibility: str | None = Field(
        default=None,
        pattern="^(all|since_join)$",
    )


class GroupMemberRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    role: str = Field(default="member", pattern="^(admin|member)$")


class GroupInvitationRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)


class GroupInvitationResponse(BaseModel):
    id: str
    chat_id: int
    inviter: str
    invitee: str
    status: str
    created_at: datetime
    expires_at: datetime


class GroupOwnerTransferRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)


class MediaObjectResponse(BaseModel):
    id: str
    purpose: Literal["attachment", "sticker"]
    size_bytes: int
    sha256: str
    is_encrypted: bool
    content_url: str


class StickerResponse(BaseModel):
    id: str
    emoji: str | None
    position: int
    image_url: str
    width: int
    height: int


class StickerPackCreate(BaseModel):
    title: str = Field(min_length=1, max_length=64)
    slug: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    visibility: Literal["public", "private"] = "private"


class StickerPackUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=64)
    visibility: Literal["public", "private"] | None = None


class StickerPackResponse(BaseModel):
    id: str
    title: str
    slug: str
    visibility: Literal["public", "private"]
    owner: str
    subscribed: bool
    editable: bool
    stickers: list[StickerResponse]
    created_at: datetime

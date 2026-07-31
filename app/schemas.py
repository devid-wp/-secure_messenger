from datetime import datetime
from typing import Literal

from pydantic import Base64Bytes, BaseModel, ConfigDict, Field


class Credentials(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    device_name: str = Field(default="Web browser", min_length=1, max_length=128)


class TokenResponse(BaseModel):
    status: str = "ok"
    token: str
    device_id: str
    device_status: str = "active"


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
    name: str | None
    created_by: str
    created_at: datetime
    members: list[str]
    member_roles: dict[str, str]
    avatar_url: str | None
    history_visibility: str
    peer: ChatPeer | None = None
    last_message: "ChatLastMessage | None" = None
    unread_count: int = 0


class ChatLastMessage(BaseModel):
    sender: str
    kind: str
    content: str
    timestamp: datetime


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=2048)
    member_logins: list[str] = Field(default_factory=list, max_length=99)
    history_visibility: str = Field(
        default="since_join",
        pattern="^(all|since_join)$",
    )


class GroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
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
    group_name: str
    inviter: str
    invitee: str
    status: str
    created_at: datetime
    expires_at: datetime


class GroupOwnerTransferRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)


class MessageResponse(BaseModel):
    id: int
    chat_id: int
    sender: str
    content: str
    kind: str
    client_id: str | None
    server_seq: int
    status: str
    reply_to_server_seq: int | None
    reply_to_sender: str | None
    reply_to_content: str | None
    timestamp: datetime
    edited_at: datetime | None
    deleted_at: datetime | None
    attachment: "MediaObjectResponse | None" = None
    sticker: "StickerResponse | None" = None
    key_envelope: str | None = None


class MessagePage(BaseModel):
    items: list[MessageResponse]
    next_cursor: str | None
    has_more: bool


class MessageEditRequest(BaseModel):
    content: str = Field(min_length=1, max_length=16384)


class MediaObjectResponse(BaseModel):
    id: str
    purpose: Literal["attachment", "sticker"]
    content_type: str
    size_bytes: int
    sha256: str
    is_encrypted: bool
    cipher: str | None
    nonce: str | None
    width: int | None
    height: int | None
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

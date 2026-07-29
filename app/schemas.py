from datetime import datetime

from pydantic import AnyHttpUrl, Base64Bytes, BaseModel, ConfigDict, Field


class Credentials(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    device_name: str = Field(default="Web browser", min_length=1, max_length=128)


class TokenResponse(BaseModel):
    status: str = "ok"
    token: str
    device_id: str


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None


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

    login: str
    created_at: datetime


class DirectChatRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)


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


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    avatar_url: AnyHttpUrl | None = None
    member_logins: list[str] = Field(default_factory=list, max_length=99)
    history_visibility: str = Field(
        default="since_join",
        pattern="^(all|since_join)$",
    )


class GroupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    avatar_url: AnyHttpUrl | None = None
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


class MessagePage(BaseModel):
    items: list[MessageResponse]
    next_cursor: str | None
    has_more: bool


class MessageEditRequest(BaseModel):
    content: str = Field(min_length=1, max_length=16384)

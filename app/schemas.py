from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class MessageResponse(BaseModel):
    id: int
    chat_id: int
    sender: str
    content: str
    client_id: str | None
    server_seq: int
    status: str
    timestamp: datetime


class MessagePage(BaseModel):
    items: list[MessageResponse]
    next_cursor: str | None
    has_more: bool

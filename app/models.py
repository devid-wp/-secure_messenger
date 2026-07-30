from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("login", name="uq_users_login"),
        UniqueConstraint("username", name="uq_users_username"),
        CheckConstraint("length(trim(login)) > 0", name="login_not_blank"),
        CheckConstraint(
            "length(username) BETWEEN 3 AND 32",
            name="username_format",
        ),
        CheckConstraint(
            "NOT is_placeholder OR NOT is_active",
            name="placeholder_inactive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(64))
    bio: Mapped[Optional[str]] = mapped_column(String(160))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(2048))
    password_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    password_salt: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    is_placeholder: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    memberships: Mapped[list["ChatMember"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    devices: Mapped[list["Device"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sticker_packs: Mapped[list["StickerPack"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    media_objects: Mapped[list["MediaObject"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 128", name="name_length"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    identity_key: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    identity_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(64),
        unique=True,
        index=True,
    )
    identity_published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    user: Mapped[User] = relationship(back_populates="devices")
    key_packages: Mapped[list["MlsKeyPackage"]] = relationship(
        back_populates="device",
        foreign_keys="MlsKeyPackage.device_id",
        cascade="all, delete-orphan",
    )


class MlsKeyPackage(Base):
    __tablename__ = "mls_key_packages"
    __table_args__ = (
        CheckConstraint("length(key_package) BETWEEN 64 AND 65536", name="size"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key_package: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    cipher_suite: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    claimed_by_device_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )

    device: Mapped[Device] = relationship(
        back_populates="key_packages",
        foreign_keys=[device_id],
    )
    claimed_by_device: Mapped[Optional[Device]] = relationship(
        foreign_keys=[claimed_by_device_id]
    )


class UserBlock(Base):
    __tablename__ = "user_blocks"
    __table_args__ = (
        CheckConstraint("blocker_id <> blocked_id", name="different_users"),
    )

    blocker_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    blocked_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    blocker: Mapped[User] = relationship(foreign_keys=[blocker_id])
    blocked: Mapped[User] = relationship(foreign_keys=[blocked_id])


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (
        CheckConstraint("type IN ('dm', 'group')", name="type"),
        CheckConstraint(
            "(type = 'dm' AND name IS NULL) OR type = 'group'",
            name="dm_has_no_name",
        ),
        CheckConstraint(
            "history_visibility IN ('all', 'since_join')",
            name="history_visibility",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(2048))
    history_visibility: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="since_join",
        server_default="since_join",
    )
    direct_key: Mapped[Optional[str]] = mapped_column(
        String(64),
        unique=True,
        index=True,
    )
    next_message_seq: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    creator: Mapped[User] = relationship(foreign_keys=[created_by_user_id])
    members: Mapped[list["ChatMember"]] = relationship(
        back_populates="chat",
        cascade="all, delete-orphan",
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="chat",
        cascade="all, delete-orphan",
    )


class ChatMember(Base):
    __tablename__ = "chat_members"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="role"),
        CheckConstraint("history_from_seq > 0", name="history_from_seq"),
    )

    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="member",
        server_default="member",
    )
    history_from_seq: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    chat: Mapped[Chat] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class ChatInvitation(Base):
    __tablename__ = "chat_invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked')",
            name="status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inviter_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    invitee_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    chat: Mapped[Chat] = relationship()
    inviter: Mapped[User] = relationship(foreign_keys=[inviter_user_id])
    invitee: Mapped[User] = relationship(foreign_keys=[invitee_user_id])


class MediaObject(Base):
    __tablename__ = "media_objects"
    __table_args__ = (
        CheckConstraint("purpose IN ('attachment', 'sticker')", name="purpose"),
        CheckConstraint("size_bytes BETWEEN 1 AND 52428800", name="size"),
        CheckConstraint(
            "(purpose = 'attachment' AND is_encrypted) OR "
            "(purpose = 'sticker' AND NOT is_encrypted)",
            name="encryption_policy",
        ),
        CheckConstraint(
            "(width IS NULL AND height IS NULL) OR "
            "(width BETWEEN 1 AND 4096 AND height BETWEEN 1 AND 4096)",
            name="dimensions",
        ),
        UniqueConstraint("object_key", name="uq_media_objects_object_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(16), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cipher: Mapped[Optional[str]] = mapped_column(String(32))
    nonce: Mapped[Optional[str]] = mapped_column(String(64))
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    owner: Mapped[User] = relationship(back_populates="media_objects")


class StickerPack(Base):
    __tablename__ = "sticker_packs"
    __table_args__ = (
        CheckConstraint("visibility IN ('public', 'private')", name="visibility"),
        CheckConstraint("length(trim(title)) BETWEEN 1 AND 64", name="title_length"),
        UniqueConstraint("owner_user_id", "slug", name="uq_sticker_packs_owner_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private", server_default="private"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    owner: Mapped[User] = relationship(back_populates="sticker_packs")
    stickers: Mapped[list["Sticker"]] = relationship(
        back_populates="pack",
        cascade="all, delete-orphan",
        order_by="Sticker.position",
    )
    subscribers: Mapped[list["StickerPackSubscription"]] = relationship(
        back_populates="pack",
        cascade="all, delete-orphan",
    )


class Sticker(Base):
    __tablename__ = "stickers"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position"),
        UniqueConstraint("pack_id", "position", name="uq_stickers_pack_position"),
        UniqueConstraint("media_object_id", name="uq_stickers_media_object"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pack_id: Mapped[str] = mapped_column(
        ForeignKey("sticker_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    media_object_id: Mapped[str] = mapped_column(
        ForeignKey("media_objects.id", ondelete="CASCADE"),
        nullable=False,
    )
    emoji: Mapped[Optional[str]] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    pack: Mapped[StickerPack] = relationship(back_populates="stickers")
    media: Mapped[MediaObject] = relationship()


class StickerPackSubscription(Base):
    __tablename__ = "sticker_pack_subscriptions"

    pack_id: Mapped[str] = mapped_column(
        ForeignKey("sticker_packs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    pack: Mapped[StickerPack] = relationship(back_populates="subscribers")
    user: Mapped[User] = relationship()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "(deleted_at IS NOT NULL AND content = '') OR "
            "(deleted_at IS NULL AND kind IN ('text', 'system') "
            "AND length(content) BETWEEN 1 AND 16384) OR "
            "(deleted_at IS NULL AND kind = 'sticker' AND content = '') OR "
            "(deleted_at IS NULL AND kind IN ('image', 'file') "
            "AND length(content) BETWEEN 0 AND 4096)",
            name="content_length",
        ),
        CheckConstraint(
            "kind IN ('text', 'sticker', 'image', 'file', 'system')",
            name="kind",
        ),
        CheckConstraint(
            "(kind = 'sticker' AND sticker_id IS NOT NULL "
            "AND attachment_id IS NULL) OR "
            "(kind IN ('image', 'file') AND attachment_id IS NOT NULL "
            "AND sticker_id IS NULL) OR "
            "(kind IN ('text', 'system') AND attachment_id IS NULL "
            "AND sticker_id IS NULL)",
            name="typed_payload",
        ),
        Index("ix_messages_chat_timestamp", "chat_id", "timestamp", "id"),
        UniqueConstraint(
            "sender_user_id",
            "client_id",
            name="uq_messages_sender_client_id",
        ),
        UniqueConstraint(
            "chat_id",
            "server_seq",
            name="uq_messages_chat_server_seq",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="text",
        server_default="text",
    )
    attachment_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"),
    )
    sticker_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("stickers.id", ondelete="RESTRICT"),
    )
    key_envelope: Mapped[Optional[str]] = mapped_column(Text)
    client_id: Mapped[Optional[str]] = mapped_column(String(36))
    server_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    reply_to_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT")
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    chat: Mapped[Chat] = relationship(back_populates="messages")
    sender: Mapped[User] = relationship()
    reply_to: Mapped[Optional["Message"]] = relationship(
        remote_side="Message.id",
        foreign_keys=[reply_to_id],
    )
    attachment: Mapped[Optional[MediaObject]] = relationship(
        foreign_keys=[attachment_id]
    )
    sticker: Mapped[Optional[Sticker]] = relationship(foreign_keys=[sticker_id])
    receipts: Mapped[list["MessageReceipt"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )


class MessageReceipt(Base):
    __tablename__ = "message_receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('delivered', 'read')",
            name="status",
        ),
    )

    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    message: Mapped[Message] = relationship(back_populates="receipts")
    user: Mapped[User] = relationship()

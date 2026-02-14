from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SqlEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BlacklistType(str, Enum):
    ip = "ip"
    phone = "phone"
    card = "card"
    email = "email"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    national_id: Mapped[str | None] = mapped_column(String(32))
    dob: Mapped[str | None] = mapped_column(String(32))
    card_number: Mapped[str | None] = mapped_column(String(32))
    kyc_status: Mapped[str] = mapped_column(String(32), default="pending")
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)


class ExchangeRequest(Base):
    __tablename__ = "exchange_requests"
    __table_args__ = (
        Index("ix_exchange_requests_status", "status"),
        Index("ix_exchange_requests_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    from_currency: Mapped[str | None] = mapped_column(String(16))
    to_currency: Mapped[str | None] = mapped_column(String(16))
    amount: Mapped[float] = mapped_column(Float)
    rate: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    risk_level: Mapped[str] = mapped_column(String(16), default="low")
    receipt_url: Mapped[str | None] = mapped_column(Text)
    payment_link: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FAQ(Base):
    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str | None] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(16), default="fa")


class BotCommand(Base):
    __tablename__ = "bot_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    response_template: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)


class BotLog(Base):
    __tablename__ = "bot_logs"
    __table_args__ = (
        Index("ix_bot_logs_timestamp", "timestamp"),
        Index("ix_bot_logs_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    command: Mapped[str | None] = mapped_column(String(128))
    response: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[str | None] = mapped_column(String(128))


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="info")
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")
    priority: Mapped[str] = mapped_column(String(32), default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_admin_id", "admin_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    old_value: Mapped[dict | None] = mapped_column(JSON)
    new_value: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Blacklist(Base):
    __tablename__ = "blacklist"
    __table_args__ = (UniqueConstraint("type", "value", name="uq_blacklist_type_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[BlacklistType] = mapped_column(SqlEnum(BlacklistType), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferralCode(Base):
    __tablename__ = "referral_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    earnings: Mapped[float] = mapped_column(Float, default=0)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    exchange_request_id: Mapped[int | None] = mapped_column(ForeignKey("exchange_requests.id"))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSegment(Base):
    __tablename__ = "user_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    criteria_json: Mapped[dict | None] = mapped_column(JSON)
    user_count: Mapped[int] = mapped_column(Integer, default=0)


class SystemConfig(Base):
    __tablename__ = "system_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    value: Mapped[dict | str | None] = mapped_column(JSON)
    category: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)


class RiskScore(Base):
    __tablename__ = "risk_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    score: Mapped[int] = mapped_column(Integer, default=0)
    factors_json: Mapped[dict | None] = mapped_column(JSON)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminSecuritySetting(Base):
    __tablename__ = "admin_security_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="Moderator")
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64))


class PasswordResetOtp(Base):
    __tablename__ = "password_reset_otps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    phone: Mapped[str | None] = mapped_column(String(32))
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoginFailure(Base):
    __tablename__ = "login_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("phone", "ip_address", name="uq_login_failures_phone_ip"),)


class ExternalApiConfig(Base):
    __tablename__ = "external_api_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    proxy_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

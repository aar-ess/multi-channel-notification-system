import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    user_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    urgency: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)

    dedup_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # manual, automatic, or scheduled
    notification_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="automatic"
    )

    # Time at which a scheduled notification should be delivered
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
    )

    status: Mapped[str] = mapped_column(
        String,
        default="pending"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    notification_id: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    channel: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    attempted_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "channel",
            name="uq_notif_channel"
        ),
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        String,
        primary_key=True
    )

    channel_priority: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    quiet_hours_start: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    quiet_hours_end: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )

    opted_out_channels: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True
    )


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    notification_id: Mapped[str] = mapped_column(
        String,
        nullable=False
    )

    triggered_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    reason: Mapped[str] = mapped_column(
        String,
        nullable=False
    )
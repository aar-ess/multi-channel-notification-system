import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    user_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    urgency = Column(String, nullable=False)
    message = Column(String, nullable=False)

    dedup_key = Column(String, nullable=True)

    # manual, automatic, or scheduled
    notification_type = Column(
        String,
        nullable=False,
        default="automatic"
    )

    # Time at which a scheduled notification should be delivered
    scheduled_at = Column(
        DateTime,
        nullable=True
    )

    status = Column(
        String,
        default="pending"
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    notification_id = Column(
        String,
        nullable=False
    )

    channel = Column(
        String,
        nullable=False
    )

    status = Column(
        String,
        nullable=False
    )

    attempted_at = Column(
        DateTime,
        default=datetime.utcnow
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

    user_id = Column(
        String,
        primary_key=True
    )

    channel_priority = Column(
        String,
        nullable=True
    )

    quiet_hours_start = Column(
        String,
        nullable=True
    )

    quiet_hours_end = Column(
        String,
        nullable=True
    )

    opted_out_channels = Column(
        String,
        nullable=True
    )


class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    notification_id = Column(
        String,
        nullable=False
    )

    triggered_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    reason = Column(
        String,
        nullable=False
    )
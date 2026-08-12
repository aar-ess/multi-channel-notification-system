import uuid
from datetime import datetime

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

from app.database import create_tables, SessionLocal
from app.models.notification import (
    Notification,
    UserPreference,
)
from app.services.dispatcher import dispatch_notification


app = FastAPI(
    title="Multi-Channel Notification Delivery System"
)


create_tables()


class NotificationIn(BaseModel):
    user_id: str
    event_type: str
    urgency: str
    message: str
    dedup_key: str | None = None
    force_fail_channels: list[str] = []


class PreferenceIn(BaseModel):
    channel_priority: list[str] | None = None
    opted_out_channels: list[str] | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None


@app.get("/health")
def health_check():
    return {"status": "ok"}


def is_quiet_hours(
    current_time,
    start_time,
    end_time
):
    if not start_time or not end_time:
        return False

    try:
        start = datetime.strptime(
            start_time,
            "%H:%M"
        ).time()

        end = datetime.strptime(
            end_time,
            "%H:%M"
        ).time()

    except ValueError:
        return False

    # Normal quiet-hours period, e.g. 22:00 -> 07:00
    if start > end:
        return (
            current_time >= start
            or current_time < end
        )

    # Same-day period, e.g. 13:00 -> 14:00
    return start <= current_time < end


async def run_dispatch(
    notif_id,
    force_fail_channels
):
    db = SessionLocal()

    try:
        notification = db.get(
            Notification,
            notif_id
        )

        if notification is None:
            return

        preference = db.get(
            UserPreference,
            notification.user_id
        )

        preferred_channels = [
            "push",
            "sms",
            "email"
        ]

        opted_out_channels = []

        if preference:

            if preference.channel_priority:
                preferred_channels = [
                    channel.strip()
                    for channel in
                    preference.channel_priority.split(",")
                    if channel.strip()
                ]

            if preference.opted_out_channels:
                opted_out_channels = [
                    channel.strip()
                    for channel in
                    preference.opted_out_channels.split(",")
                    if channel.strip()
                ]

            # Check quiet hours before attempting delivery.
            current_time = datetime.now().time()

            if is_quiet_hours(
                current_time,
                preference.quiet_hours_start,
                preference.quiet_hours_end
            ):
                notification.status = (
                    "deferred_quiet_hours"
                )
                db.commit()
                print(
                    "NOTIFICATION DEFERRED: "
                    "quiet hours active"
                )
                return

        result = await dispatch_notification(
            notification,
            force_fail_channels,
            preferred_channels,
            opted_out_channels
        )

        notification.status = result["status"]

        db.commit()

    finally:
        db.close()


@app.post("/notifications", status_code=202)
async def submit_notification(
    payload: NotificationIn,
    background_tasks: BackgroundTasks
):
    db = SessionLocal()

    try:
        # Check for duplicate notification.
        if payload.dedup_key:

            existing = (
                db.query(Notification)
                .filter(
                    Notification.user_id == payload.user_id,
                    Notification.dedup_key == payload.dedup_key
                )
                .first()
            )

            if existing:
                return {
                    "id": existing.id,
                    "status": "duplicate",
                    "message": "Notification already exists"
                }

        notif_id = str(uuid.uuid4())

        notification = Notification(
            id=notif_id,
            user_id=payload.user_id,
            event_type=payload.event_type,
            urgency=payload.urgency,
            message=payload.message,
            dedup_key=payload.dedup_key,
            status="pending"
        )

        db.add(notification)
        db.commit()

    finally:
        db.close()

    background_tasks.add_task(
        run_dispatch,
        notif_id,
        payload.force_fail_channels
    )

    return {
        "id": notif_id,
        "status": "pending"
    }


@app.get("/notifications/{notification_id}")
def get_notification_status(
    notification_id: str
):
    db = SessionLocal()

    try:
        notification = db.get(
            Notification,
            notification_id
        )

        if notification is None:
            return {
                "error": "Notification not found"
            }

        return {
            "id": notification.id,
            "status": notification.status
        }

    finally:
        db.close()


@app.put("/preferences/{user_id}")
def update_preferences(
    user_id: str,
    payload: PreferenceIn
):
    db = SessionLocal()

    try:
        preference = db.get(
            UserPreference,
            user_id
        )

        if preference is None:
            preference = UserPreference(
                user_id=user_id
            )
            db.add(preference)

        if payload.channel_priority is not None:
            preference.channel_priority = ",".join(
                payload.channel_priority
            )

        if payload.opted_out_channels is not None:
            preference.opted_out_channels = ",".join(
                payload.opted_out_channels
            )

        if payload.quiet_hours_start is not None:
            preference.quiet_hours_start = (
                payload.quiet_hours_start
            )

        if payload.quiet_hours_end is not None:
            preference.quiet_hours_end = (
                payload.quiet_hours_end
            )

        db.commit()

        return {
            "user_id": user_id,
            "channel_priority": (
                preference.channel_priority.split(",")
                if preference.channel_priority
                else []
            ),
            "opted_out_channels": (
                preference.opted_out_channels.split(",")
                if preference.opted_out_channels
                else []
            ),
            "quiet_hours_start": (
                preference.quiet_hours_start
            ),
            "quiet_hours_end": (
                preference.quiet_hours_end
            )
        }

    finally:
        db.close()


@app.get("/preferences/{user_id}")
def get_preferences(user_id: str):
    db = SessionLocal()

    try:
        preference = db.get(
            UserPreference,
            user_id
        )

        if preference is None:
            return {
                "user_id": user_id,
                "channel_priority": [
                    "push",
                    "sms",
                    "email"
                ],
                "opted_out_channels": [],
                "quiet_hours_start": None,
                "quiet_hours_end": None
            }

        return {
            "user_id": user_id,
            "channel_priority": (
                preference.channel_priority.split(",")
                if preference.channel_priority
                else []
            ),
            "opted_out_channels": (
                preference.opted_out_channels.split(",")
                if preference.opted_out_channels
                else []
            ),
            "quiet_hours_start": (
                preference.quiet_hours_start
            ),
            "quiet_hours_end": (
                preference.quiet_hours_end
            )
        }

    finally:
        db.close()
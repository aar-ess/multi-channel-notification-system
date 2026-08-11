import uuid

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

from app.database import create_tables, SessionLocal
from app.models.notification import Notification
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


@app.get("/health")
def health_check():
    return {"status": "ok"}


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

        result = await dispatch_notification(
            notification,
            force_fail_channels
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
        # Check for an existing notification with the same
        # deduplication key for this user.
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
def get_notification_status(notification_id: str):
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
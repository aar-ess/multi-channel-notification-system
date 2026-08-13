import asyncio
from datetime import datetime

from app.database import SessionLocal
from app.models.notification import Notification, UserPreference
import app.main as main


def test_urgent_notification_bypasses_quiet_hours(monkeypatch):

    db = SessionLocal()

    notification = Notification(
        user_id="pytest_urgent",
        event_type="security_alert",
        urgency="urgent",
        message="Urgent test",
        dedup_key=None,
        notification_type="automatic",
        status="pending",
    )

    preference = UserPreference(
        user_id="pytest_urgent",
        channel_priority="push,sms,email",
        opted_out_channels="",
        quiet_hours_start="00:00",
        quiet_hours_end="23:59",
    )

    db.add(notification)
    db.add(preference)
    db.commit()
    db.refresh(notification)

    notification_id = notification.id
    db.close()

    dispatched = False

    async def fake_dispatch(
        notification,
        force_fail_channels=None,
        preferred_channels=None,
        opted_out_channels=None,
    ):
        nonlocal dispatched
        dispatched = True

        return {
            "status": "delivered",
            "channel": "push",
        }

    monkeypatch.setattr(
        main,
        "dispatch_notification",
        fake_dispatch,
    )

    asyncio.run(
        main.run_dispatch(
            notification_id,
            [],
        )
    )

    assert dispatched

    db = SessionLocal()

    try:
        notification = db.get(
            Notification,
            notification_id,
        )
        
        assert notification is not None
        assert notification.status == "delivered"

    finally:
        preference = db.get(
            UserPreference,
            "pytest_urgent",
        )

        if preference:
            db.delete(preference)

        if notification:
            db.delete(notification)

        db.commit()
        db.close()
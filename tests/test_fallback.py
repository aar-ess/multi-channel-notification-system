import asyncio

from app.database import SessionLocal
from app.models.notification import Notification, DeliveryAttempt
import app.services.dispatcher as dispatcher


def test_push_failure_falls_back_to_sms(monkeypatch):
    db = SessionLocal()

    notification = Notification(
        user_id="pytest_fallback",
        event_type="fallback_test",
        urgency="normal",
        message="Fallback test",
        dedup_key=None,
        notification_type="automatic",
        status="pending",
    )

    db.add(notification)
    db.commit()
    db.refresh(notification)

    notification_id = notification.id
    db.close()

    async def fake_push(notification, force_fail=False):
        return {
            "status": "failed",
            "channel": "push",
        }

    async def fake_sms(notification, force_fail=False):
        return {
            "status": "sent",
            "channel": "sms",
        }

    monkeypatch.setattr(
        dispatcher,
        "send_push",
        fake_push,
    )

    monkeypatch.setattr(
        dispatcher,
        "send_sms",
        fake_sms,
    )

    async def run_test():
        db = SessionLocal()

        try:
            notification = db.get(
                Notification,
                notification_id,
            )

            return await dispatcher.dispatch_notification(
                notification,
                preferred_channels=["push", "sms"],
            )

        finally:
            db.close()

    result = asyncio.run(run_test())

    assert result["status"] == "delivered"
    assert result["channel"] == "sms"

    db = SessionLocal()
    attempts = []

    try:
        attempts = (
            db.query(DeliveryAttempt)
            .filter(
                DeliveryAttempt.notification_id
                == notification_id
            )
            .all()
        )

        statuses = {
            attempt.channel: attempt.status
            for attempt in attempts
        }

        assert statuses["push"] == "failed"
        assert statuses["sms"] == "sent"

    finally:
        for attempt in attempts:
            db.delete(attempt)

        notification = db.get(
            Notification,
            notification_id,
        )

        if notification:
            db.delete(notification)

        db.commit()
        db.close()
import asyncio

from app.database import SessionLocal
from app.models.notification import Notification, DeliveryAttempt, Escalation
import app.services.dispatcher as dispatcher


def test_urgent_notification_escalates_after_all_channels_fail(monkeypatch):

    db = SessionLocal()

    notification = Notification(
        user_id="pytest_escalation",
        event_type="security_alert",
        urgency="urgent",
        message="Escalation test",
        dedup_key=None,
        notification_type="automatic",
        status="pending",
    )

    db.add(notification)
    db.commit()
    db.refresh(notification)

    notification_id = notification.id
    db.close()

    async def failed_channel(notification, force_fail=False):
        return {
            "status": "failed",
            "channel": "test",
        }

    monkeypatch.setattr(
        dispatcher,
        "send_push",
        failed_channel,
    )

    monkeypatch.setattr(
        dispatcher,
        "send_sms",
        failed_channel,
    )

    monkeypatch.setattr(
        dispatcher,
        "send_email",
        failed_channel,
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
                preferred_channels=[
                    "push",
                    "sms",
                    "email",
                ],
            )

        finally:
            db.close()

    result = asyncio.run(run_test())

    assert result["status"] == "all_channels_failed"

    db = SessionLocal()
    escalation = None

    try:
        escalation = (
            db.query(Escalation)
            .filter(
                Escalation.notification_id
                == notification_id
            )
            .first()
        )

        assert escalation is not None
        assert (
            escalation.reason
            == "All channels failed or timed out"
        )

    finally:
        attempts = (
            db.query(DeliveryAttempt)
            .filter(
                DeliveryAttempt.notification_id
                == notification_id
            )
            .all()
        )

        for attempt in attempts:
            db.delete(attempt)

        if escalation:
            db.delete(escalation)

        notification = db.get(
            Notification,
            notification_id,
        )

        if notification:
            db.delete(notification)

        db.commit()
        db.close()
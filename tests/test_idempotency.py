import asyncio

from app.database import SessionLocal
from app.models.notification import Notification, DeliveryAttempt
import app.services.dispatcher as dispatcher


def test_concurrent_dispatch_does_not_duplicate(monkeypatch):

    db = SessionLocal()

    notification = Notification(
        user_id="pytest_idempotency",
        event_type="idempotency_test",
        urgency="normal",
        message="pytest idempotency test",
        dedup_key=None,
        notification_type="automatic",
        status="pending",
    )

    db.add(notification)
    db.commit()
    db.refresh(notification)

    notification_id = notification.id
    db.close()

    send_count = 0

    async def fake_push(notification, force_fail=False):
        nonlocal send_count
        send_count += 1
        await asyncio.sleep(0.1)

        return {
            "status": "sent",
            "channel": "push",
        }

    monkeypatch.setattr(
        dispatcher,
        "send_push",
        fake_push,
    )

    async def run_test():

        db1 = SessionLocal()
        db2 = SessionLocal()

        try:
            notification1 = db1.get(
                Notification,
                notification_id,
            )

            notification2 = db2.get(
                Notification,
                notification_id,
            )

            await asyncio.gather(
                dispatcher.dispatch_notification(notification1),
                dispatcher.dispatch_notification(notification2),
            )

        finally:
            db1.close()
            db2.close()

    asyncio.run(run_test())

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

        assert len(attempts) == 1
        assert attempts[0].channel == "push"
        assert attempts[0].status == "sent"
        assert send_count == 1

    finally:
        # Clean up test data
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
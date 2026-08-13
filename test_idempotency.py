import asyncio

from app.database import SessionLocal
from app.models.notification import Notification, DeliveryAttempt
from app.services.dispatcher import dispatch_notification


async def main():
    db = SessionLocal()

    try:
        notification = Notification(
            user_id="concurrent_test",
            event_type="idempotency_test",
            urgency="normal",
            message="Concurrent idempotency test",
            dedup_key=None,
            notification_type="automatic",
            status="pending"
        )

        db.add(notification)
        db.commit()
        db.refresh(notification)

        notification_id = notification.id

    finally:
        db.close()

    db1 = SessionLocal()
    db2 = SessionLocal()

    try:
        notification1 = db1.get(
            Notification,
            notification_id
        )

        notification2 = db2.get(
            Notification,
            notification_id
        )

        await asyncio.gather(
            dispatch_notification(notification1),
            dispatch_notification(notification2)
        )

    finally:
        db1.close()
        db2.close()

    db = SessionLocal()

    try:
        attempts = (
            db.query(DeliveryAttempt)
            .filter(
                DeliveryAttempt.notification_id
                == notification_id
            )
            .all()
        )

        print()
        print("DeliveryAttempt rows:", len(attempts))

        for attempt in attempts:
            print(
                "Channel:",
                attempt.channel,
                "| Status:",
                attempt.status
            )

    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())

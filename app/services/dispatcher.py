import asyncio

from sqlalchemy.exc import IntegrityError

from app.services.channels import (
    send_push,
    send_sms,
    send_email,
)

from app.database import SessionLocal

from app.models.notification import (
    DeliveryAttempt,
    Escalation,
)


TIMEOUT_BUDGETS = {
    "push": 3,
    "sms": 8,
    "email": 15,
}


async def dispatch_notification(
    notification,
    force_fail_channels: list[str] | None = None,
    preferred_channels: list[str] | None = None,
    opted_out_channels: list[str] | None = None
) -> dict[str, str | None]:
    if force_fail_channels is None:
        force_fail_channels = []

    if preferred_channels is None:
        preferred_channels = [
            "push",
            "sms",
            "email"
        ]

    if opted_out_channels is None:
        opted_out_channels = []

    channel_functions = {
        "push": send_push,
        "sms": send_sms,
        "email": send_email,
    }

    channels = []

    for channel_name in preferred_channels:
        if (
            channel_name in channel_functions
            and channel_name not in opted_out_channels
        ):
            channels.append(
                (channel_name, channel_functions[channel_name])
            )

    for channel_name in [
        "push",
        "sms",
        "email"
    ]:
        if (
            channel_name not in preferred_channels
            and channel_name not in opted_out_channels
        ):
            channels.append(
                (channel_name, channel_functions[channel_name])
            )

    # If every channel is opted out, fail immediately.
    if not channels:
        if notification.urgency.lower() == "urgent":
            db = SessionLocal()

            try:
                escalation = Escalation(
                    notification_id=notification.id,
                    reason="All channels are opted out"
                )

                db.add(escalation)
                db.commit()

            finally:
                db.close()

            print(
                "ESCALATION: urgent notification "
                "has no available channels"
            )

        return {
            "status": "all_channels_failed",
            "channel": None
        }

    # Try each channel once.
    # Failure or timeout immediately moves to the next channel.
    for channel_name, sender in channels:

        db = SessionLocal()

        try:
            delivery_attempt = DeliveryAttempt(
                notification_id=notification.id,
                channel=channel_name,
                status="in_progress"
            )

            db.add(delivery_attempt)

            try:
                db.commit()

            except IntegrityError:
                db.rollback()

                print(
                    f"{channel_name.upper()}: "
                    "already claimed, skipping duplicate dispatch"
                )

                return {
                    "status": "already_processing",
                    "channel": channel_name
                }

        finally:
            db.close()

        should_fail = (
            channel_name in force_fail_channels
        )

        try:
            result = await asyncio.wait_for(
                sender(
                    notification,
                    force_fail=should_fail
                ),
                timeout=TIMEOUT_BUDGETS[channel_name]
            )

        except asyncio.TimeoutError:
            result = {
                "status": "timeout",
                "channel": channel_name
            }

        except Exception:
            result = {
                "status": "failed",
                "channel": channel_name
            }

        print(
            f"{channel_name.upper()}: "
            f"{result['status']}"
        )

        db = SessionLocal()

        try:
            delivery_attempt = (
                db.query(DeliveryAttempt)
                .filter(
                    DeliveryAttempt.notification_id
                    == notification.id,
                    DeliveryAttempt.channel
                    == channel_name
                )
                .first()
            )

            if delivery_attempt:
                delivery_attempt.status = (
                    result["status"]
                )

            db.commit()

        finally:
            db.close()

        if result["status"] == "sent":
            return {
                "status": "delivered",
                "channel": channel_name
            }

        # Otherwise immediately continue to next channel.

    # Every available channel failed/timed out.
    if notification.urgency.lower() == "urgent":

        db = SessionLocal()

        try:
            escalation = Escalation(
                notification_id=notification.id,
                reason="All channels failed or timed out"
            )

            db.add(escalation)
            db.commit()

        finally:
            db.close()

        print(
            "ESCALATION: urgent notification "
            "failed on all channels"
        )

    return {
        "status": "all_channels_failed",
        "channel": None
    }
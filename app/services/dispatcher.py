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


MAX_RETRIES = 2


async def dispatch_notification(
    notification,
    force_fail_channels=None,
    preferred_channels=None,
    opted_out_channels=None
):
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

    # Build delivery order using user preferences.
    channels = []

    for channel_name in preferred_channels:
        if (
            channel_name in channel_functions
            and channel_name not in opted_out_channels
        ):
            channels.append(
                (
                    channel_name,
                    channel_functions[channel_name]
                )
            )

    # Add remaining available channels.
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
                (
                    channel_name,
                    channel_functions[channel_name]
                )
            )

    # Try each channel.
    for channel_index, (
        channel_name,
        sender
    ) in enumerate(channels):

        channel_succeeded = False

        # Retry the current channel up to MAX_RETRIES times.
        for attempt_number in range(
            1,
            MAX_RETRIES + 1
        ):

            should_fail = (
                channel_name in force_fail_channels
            )

            result = await sender(
                notification,
                force_fail=should_fail
            )

            print(
                f"{channel_name.upper()} "
                f"ATTEMPT {attempt_number}: "
                f"{result['status']}"
            )

            db = SessionLocal()

            try:
                existing_attempt = (
                    db.query(DeliveryAttempt)
                    .filter(
                        DeliveryAttempt.notification_id
                        == notification.id,
                        DeliveryAttempt.channel
                        == channel_name
                    )
                    .first()
                )

                if existing_attempt:
                    existing_attempt.status = (
                        result["status"]
                    )
                else:
                    delivery_attempt = DeliveryAttempt(
                        notification_id=notification.id,
                        channel=channel_name,
                        status=result["status"]
                    )

                    db.add(delivery_attempt)

                db.commit()

            finally:
                db.close()

            if result["status"] == "sent":
                channel_succeeded = True

                return {
                    "status": "delivered",
                    "channel": channel_name
                }

        # Current channel failed after all retries.
        # Escalate to the next available channel.
        if not channel_succeeded:

            next_channel = None

            if channel_index + 1 < len(channels):
                next_channel = channels[
                    channel_index + 1
                ][0]

            db = SessionLocal()

            try:
                escalation = Escalation(
                    notification_id=notification.id,
                    reason=(
                        f"{channel_name} failed "
                        f"after {MAX_RETRIES} attempts"
                    )
                )

                db.add(escalation)
                db.commit()

            finally:
                db.close()

            if next_channel:
                print(
                    f"ESCALATING: "
                    f"{channel_name.upper()} -> "
                    f"{next_channel.upper()}"
                )

    return {
        "status": "all_channels_failed",
        "channel": None
    }
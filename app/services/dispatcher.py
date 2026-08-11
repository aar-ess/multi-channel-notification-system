from app.services.channels import (
    send_push,
    send_sms,
    send_email,
)


async def dispatch_notification(
    notification,
    force_fail_channels=None
):
    if force_fail_channels is None:
        force_fail_channels = []

    channels = [
        ("push", send_push),
        ("sms", send_sms),
        ("email", send_email),
    ]

    for channel_name, sender in channels:

        should_fail = channel_name in force_fail_channels

        result = await sender(
            notification,
            force_fail=should_fail
        )

        print(
            f"{channel_name.upper()}: "
            f"{result['status']}"
        )

        if result["status"] == "sent":
            return {
                "status": "delivered",
                "channel": channel_name
            }

    return {
        "status": "all_channels_failed",
        "channel": None
    }
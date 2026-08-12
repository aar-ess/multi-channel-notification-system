from app.services.channels import (
    send_push,
    send_sms,
    send_email,
)


async def dispatch_notification(
    notification,
    force_fail_channels=None,
    preferred_channels=None,
    opted_out_channels=None
):
    if force_fail_channels is None:
        force_fail_channels = []

    if preferred_channels is None:
        preferred_channels = ["push", "sms", "email"]

    if opted_out_channels is None:
        opted_out_channels = []

    channel_functions = {
        "push": send_push,
        "sms": send_sms,
        "email": send_email,
    }

    # Build the delivery order from user preferences.
    channels = []

    for channel_name in preferred_channels:
        if (
            channel_name in channel_functions
            and channel_name not in opted_out_channels
        ):
            channels.append(
                (channel_name, channel_functions[channel_name])
            )

    # Add any remaining channels using the default order.
    for channel_name in ["push", "sms", "email"]:
        if (
            channel_name not in preferred_channels
            and channel_name not in opted_out_channels
        ):
            channels.append(
                (channel_name, channel_functions[channel_name])
            )

    # Try channels in the selected order.
    for channel_name, sender in channels:

        should_fail = (
            channel_name in force_fail_channels
        )

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
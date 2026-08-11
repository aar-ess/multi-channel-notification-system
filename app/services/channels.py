import asyncio


async def send_push(notification, force_fail=False):
    await asyncio.sleep(0.5)

    if force_fail:
        return {"status": "failed", "channel": "push"}

    return {"status": "sent", "channel": "push"}


async def send_sms(notification, force_fail=False):
    await asyncio.sleep(1.5)

    if force_fail:
        return {"status": "failed", "channel": "sms"}

    return {"status": "sent", "channel": "sms"}


async def send_email(notification, force_fail=False):
    await asyncio.sleep(2.0)

    if force_fail:
        return {"status": "failed", "channel": "email"}

    return {"status": "sent", "channel": "email"}
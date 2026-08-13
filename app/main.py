import asyncio
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import (
    FastAPI,
    BackgroundTasks,
    Depends,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth import verify_api_key

from app.database import (
    create_tables,
    SessionLocal,
)

from app.models.notification import (
    Notification,
    DeliveryAttempt,
    UserPreference,
    Escalation,
)

from app.services.dispatcher import (
    dispatch_notification,
)


app = FastAPI(
    title="Multi-Channel Notification Delivery System"
)


create_tables()


# ============================================================
# DASHBOARD
# ============================================================

DASHBOARD_PATH = (
    Path(__file__).resolve().parent
    / "dashboard"
    / "index.html"
)


@app.get("/dashboard")
def dashboard():
    return FileResponse(DASHBOARD_PATH)


@app.get("/dashboard/stats")
def dashboard_stats(
    api_key: str = Depends(verify_api_key)
):
    from collections import defaultdict

    db = SessionLocal()

    try:
        notifications = (
            db.query(Notification)
            .order_by(
                Notification.created_at.desc()
            )
            .all()
        )

        total = len(notifications)

        delivered = sum(
            1
            for n in notifications
            if n.status == "delivered"
        )

        failed = sum(
            1
            for n in notifications
            if n.status == "all_channels_failed"
        )

        deferred = sum(
            1
            for n in notifications
            if n.status == "deferred_quiet_hours"
        )

        # ── Escalations ──────────────────────────────────────
        escalation_rows = (
            db.query(Escalation)
            .order_by(
                Escalation.triggered_at.desc()
            )
            .limit(10)
            .all()
        )

        escalated = len(
            {e.notification_id for e in escalation_rows}
        )

        escalations = [
            {
                "notification_id": e.notification_id,
                "reason": e.reason,
                "triggered_at": (
                    e.triggered_at.isoformat()
                    if e.triggered_at
                    else None
                ),
            }
            for e in escalation_rows
        ]

        # ── Delivery attempts ─────────────────────────────────
        attempts = db.query(DeliveryAttempt).all()

        channel_stats: dict = {
            "push":  {"total": 0, "success": 0, "failed": 0},
            "sms":   {"total": 0, "success": 0, "failed": 0},
            "email": {"total": 0, "success": 0, "failed": 0},
        }

        for attempt in attempts:
            ch = attempt.channel
            if ch in channel_stats:
                channel_stats[ch]["total"] += 1
                if attempt.status == "sent":
                    channel_stats[ch]["success"] += 1
                elif attempt.status in ("failed", "timeout"):
                    channel_stats[ch]["failed"] += 1

        # ── Fallback detection ────────────────────────────────
        # A fallback occurs when a channel's DeliveryAttempt
        # has status failed/timeout and another attempt exists
        # for the same notification on the next channel tried.
        attempts_by_notif: dict = defaultdict(list)

        for attempt in attempts:
            attempts_by_notif[
                attempt.notification_id
            ].append(attempt)

        fallbacks = []

        for notif_id, notif_attempts in attempts_by_notif.items():
            sorted_a = sorted(
                notif_attempts,
                key=lambda a: a.attempted_at or datetime.min,
            )

            for i in range(len(sorted_a) - 1):
                cur = sorted_a[i]
                nxt = sorted_a[i + 1]

                if cur.status in ("failed", "timeout"):
                    fallbacks.append(
                        {
                            "notification_id": notif_id,
                            "from_channel": cur.channel,
                            "to_channel": nxt.channel,
                            "reason": cur.status,
                        }
                    )

        # Keep the 20 most recent fallback events
        fallbacks = fallbacks[-20:]

        # ── Success rate ──────────────────────────────────────
        success_rate = round(
            (delivered / total * 100)
            if total > 0
            else 0.0,
            1,
        )

        # ── Recent notifications ──────────────────────────────
        recent = [
            {
                "id": n.id,
                "event_type": n.event_type,
                "user_id": n.user_id,
                "urgency": n.urgency,
                "status": n.status,
                "notification_type": n.notification_type,
            }
            for n in notifications[:10]
        ]

        return {
            "total": total,
            "delivered": delivered,
            "failed": failed,
            "deferred": deferred,
            "escalated": escalated,
            "success_rate": success_rate,
            "channels": channel_stats,
            "fallbacks": fallbacks,
            "escalations": escalations,
            "recent": recent,
        }

    finally:
        db.close()


# ============================================================
# PYDANTIC MODELS
# ============================================================


class NotificationIn(BaseModel):
    user_id: str
    event_type: str
    urgency: str
    message: str
    dedup_key: str | None = None

    notification_type: str = "automatic"

    scheduled_at: datetime | None = None

    force_fail_channels: list[str] = []


class PreferenceIn(BaseModel):
    channel_priority: list[str] | None = None

    opted_out_channels: list[str] | None = None

    quiet_hours_start: str | None = None

    quiet_hours_end: str | None = None


# ============================================================
# HEALTH CHECK
# ============================================================


@app.get("/health")
def health_check():
    return {
        "status": "ok"
    }


# ============================================================
# QUIET HOURS
# ============================================================


def is_quiet_hours(
    current_time,
    start_time,
    end_time
):
    if not start_time or not end_time:
        return False

    try:
        start = datetime.strptime(
            start_time,
            "%H:%M"
        ).time()

        end = datetime.strptime(
            end_time,
            "%H:%M"
        ).time()

    except ValueError:
        return False

    if start > end:
        return (
            current_time >= start
            or current_time < end
        )

    return (
        start <= current_time < end
    )


def seconds_until_quiet_hours_end(
    current_datetime,
    end_time
):
    end = datetime.strptime(
        end_time,
        "%H:%M"
    ).time()

    end_datetime = datetime.combine(
        current_datetime.date(),
        end
    )

    if end_datetime <= current_datetime:
        end_datetime += timedelta(days=1)

    return (
        end_datetime - current_datetime
    ).total_seconds()


# ============================================================
# DISPATCH ORCHESTRATION
# ============================================================


async def run_dispatch(
    notif_id,
    force_fail_channels
):
    db = SessionLocal()

    try:
        notification = db.get(
            Notification,
            notif_id
        )

        if notification is None:
            return

        # ----------------------------------------------------
        # Scheduled notification
        # ----------------------------------------------------

        if notification.scheduled_at:
            now = datetime.now()

            if notification.scheduled_at > now:

                wait_seconds = (
                    notification.scheduled_at - now
                ).total_seconds()

                notification.status = "scheduled"

                db.commit()

                db.close()

                await asyncio.sleep(
                    wait_seconds
                )

                db = SessionLocal()

                notification = db.get(
                    Notification,
                    notif_id
                )

                if notification is None:
                    return

        # ----------------------------------------------------
        # Load user preferences
        # ----------------------------------------------------

        preference = db.get(
            UserPreference,
            notification.user_id
        )

        preferred_channels = [
            "push",
            "sms",
            "email",
        ]

        opted_out_channels = []

        if preference:

            # ------------------------------------------------
            # Channel priority
            # ------------------------------------------------

            if preference.channel_priority:

                preferred_channels = [
                    channel.strip()
                    for channel in
                    preference.channel_priority.split(",")
                    if channel.strip()
                ]

            # ------------------------------------------------
            # Opt-outs
            # ------------------------------------------------

            if preference.opted_out_channels:

                opted_out_channels = [
                    channel.strip()
                    for channel in
                    preference.opted_out_channels.split(",")
                    if channel.strip()
                ]

            # ------------------------------------------------
            # Quiet hours
            # ------------------------------------------------

            if notification.urgency.lower() != "urgent":

                current_datetime = datetime.now()

                if is_quiet_hours(
                    current_datetime.time(),
                    preference.quiet_hours_start,
                    preference.quiet_hours_end
                ):

                    notification.status = (
                        "deferred_quiet_hours"
                    )

                    db.commit()

                    print(
                        "NOTIFICATION DEFERRED: "
                        "quiet hours active"
                    )

                    quiet_hours_end = (
                        preference.quiet_hours_end
                    )

                    db.close()

                    wait_seconds = (
                        seconds_until_quiet_hours_end(
                            current_datetime,
                            quiet_hours_end
                        )
                    )

                    await asyncio.sleep(
                        wait_seconds
                    )

                    db = SessionLocal()

                    notification = db.get(
                        Notification,
                        notif_id
                    )

                    if notification is None:
                        return

                    print(
                        "QUIET HOURS ENDED: "
                        "resuming notification dispatch"
                    )

        # ----------------------------------------------------
        # Dispatch
        # ----------------------------------------------------

        result = await dispatch_notification(
            notification,
            force_fail_channels,
            preferred_channels,
            opted_out_channels
        )

        # ----------------------------------------------------
        # Update final status
        # ----------------------------------------------------

        status = result["status"]
        if status is not None and status != "already_processing":
            notification.status = status
            db.commit()

    finally:
        db.close()


# ============================================================
# CREATE NOTIFICATION
# ============================================================


@app.post(
    "/notifications",
    status_code=202
)
async def submit_notification(
    payload: NotificationIn,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(
        verify_api_key
    )
):

    valid_types = {
        "manual",
        "automatic",
        "scheduled",
    }

    # --------------------------------------------------------
    # Validate notification type
    # --------------------------------------------------------

    if payload.notification_type not in valid_types:

        return {
            "error": (
                "notification_type must be "
                "manual, automatic, or scheduled"
            )
        }

    # --------------------------------------------------------
    # Scheduled notification validation
    # --------------------------------------------------------

    if (
        payload.notification_type == "scheduled"
        and payload.scheduled_at is None
    ):

        return {
            "error": (
                "scheduled_at is required "
                "for scheduled notifications"
            )
        }

    db = SessionLocal()

    try:

        # ----------------------------------------------------
        # Submission-level deduplication
        # ----------------------------------------------------

        if payload.dedup_key:

            existing = (
                db.query(Notification)
                .filter(
                    Notification.user_id
                    == payload.user_id,

                    Notification.dedup_key
                    == payload.dedup_key,
                )
                .first()
            )

            if existing:

                return {
                    "id": existing.id,
                    "status": "duplicate",
                    "message": (
                        "Notification already exists"
                    ),
                }

        # ----------------------------------------------------
        # Create notification
        # ----------------------------------------------------

        notif_id = str(
            uuid.uuid4()
        )

        notification = Notification(
            id=notif_id,

            user_id=payload.user_id,

            event_type=payload.event_type,

            urgency=payload.urgency,

            message=payload.message,

            dedup_key=payload.dedup_key,

            notification_type=(
                payload.notification_type
            ),

            scheduled_at=(
                payload.scheduled_at
            ),

            status=(
                "scheduled"
                if payload.scheduled_at
                else "pending"
            ),
        )

        db.add(notification)

        db.commit()

    finally:
        db.close()

    # --------------------------------------------------------
    # Background dispatch
    # --------------------------------------------------------

    background_tasks.add_task(
        run_dispatch,
        notif_id,
        payload.force_fail_channels,
    )

    return {
        "id": notif_id,

        "status": (
            "scheduled"
            if payload.scheduled_at
            else "pending"
        ),

        "notification_type": (
            payload.notification_type
        ),
    }


# ============================================================
# GET NOTIFICATION
# ============================================================


@app.get(
    "/notifications/{notification_id}"
)
def get_notification_status(
    notification_id: str,

    api_key: str = Depends(
        verify_api_key
    )
):

    db = SessionLocal()

    try:

        notification = db.get(
            Notification,
            notification_id
        )

        if notification is None:

            return {
                "error": (
                    "Notification not found"
                )
            }

        return {
            "id": notification.id,

            "status": notification.status,

            "notification_type": (
                notification.notification_type
            ),

            "scheduled_at": (
                notification.scheduled_at
            ),
        }

    finally:
        db.close()


# ============================================================
# UPDATE USER PREFERENCES
# ============================================================


@app.put(
    "/preferences/{user_id}"
)
def update_preferences(
    user_id: str,

    payload: PreferenceIn,

    api_key: str = Depends(
        verify_api_key
    )
):

    db = SessionLocal()

    try:

        preference = db.get(
            UserPreference,
            user_id
        )

        if preference is None:

            preference = UserPreference(
                user_id=user_id
            )

            db.add(preference)

        # ----------------------------------------------------
        # Channel priority
        # ----------------------------------------------------

        if payload.channel_priority is not None:

            preference.channel_priority = (
                ",".join(
                    payload.channel_priority
                )
            )

        # ----------------------------------------------------
        # Opted-out channels
        # ----------------------------------------------------

        if payload.opted_out_channels is not None:

            preference.opted_out_channels = (
                ",".join(
                    payload.opted_out_channels
                )
            )

        # ----------------------------------------------------
        # Quiet hours
        # ----------------------------------------------------

        if payload.quiet_hours_start is not None:

            preference.quiet_hours_start = (
                payload.quiet_hours_start
            )

        if payload.quiet_hours_end is not None:

            preference.quiet_hours_end = (
                payload.quiet_hours_end
            )

        db.commit()

        return {
            "user_id": user_id,

            "channel_priority": (
                preference.channel_priority.split(",")
                if preference.channel_priority
                else []
            ),

            "opted_out_channels": (
                preference.opted_out_channels.split(",")
                if preference.opted_out_channels
                else []
            ),

            "quiet_hours_start": (
                preference.quiet_hours_start
            ),

            "quiet_hours_end": (
                preference.quiet_hours_end
            ),
        }

    finally:
        db.close()


# ============================================================
# GET USER PREFERENCES
# ============================================================


@app.get(
    "/preferences/{user_id}"
)
def get_preferences(
    user_id: str,

    api_key: str = Depends(
        verify_api_key
    )
):

    db = SessionLocal()

    try:

        preference = db.get(
            UserPreference,
            user_id
        )

        if preference is None:

            return {
                "user_id": user_id,

                "channel_priority": [
                    "push",
                    "sms",
                    "email",
                ],

                "opted_out_channels": [],

                "quiet_hours_start": None,

                "quiet_hours_end": None,
            }

        return {
            "user_id": user_id,

            "channel_priority": (
                preference.channel_priority.split(",")
                if preference.channel_priority
                else []
            ),

            "opted_out_channels": (
                preference.opted_out_channels.split(",")
                if preference.opted_out_channels
                else []
            ),

            "quiet_hours_start": (
                preference.quiet_hours_start
            ),

            "quiet_hours_end": (
                preference.quiet_hours_end
            ),
        }

    finally:
        db.close()
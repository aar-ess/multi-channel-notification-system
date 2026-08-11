# Design Document

## Problem Summary

Deliver a notification to a user through one of several channels, with automatic fallback if a channel is slow, fails, or silently drops the message, while preventing duplicate sends through a given channel and without letting a security-class notification vanish if every channel fails.

## Architecture Overview

The system consists of the following components:

- **Client** — submits notifications to the service.
- **FastAPI Service** — provides the notification API.
- **SQLite** — stores notifications, delivery attempts, and user preferences.
- **Fallback Dispatcher** — selects channels and controls the delivery sequence.
- **Push, SMS, and Email** — mocked notification channels.
- **Escalation Logger** — records escalation events when an urgent notification cannot be delivered through any channel.

### System Flow

The client sends a notification to the FastAPI service through `POST /notifications`.

The service stores the notification in SQLite and passes it to the fallback dispatcher. The dispatcher resolves the user's preferred channel order, removes opted-out channels, and attempts delivery through each available channel.

If a channel fails or times out, the dispatcher moves to the next channel. If all channels fail, the notification is marked as `all_channels_failed`. For urgent notifications, an additional escalation event is generated.

## Core Entities

### Notification

Stores:

- `id` — UUID
- `user_id`
- `event_type`
- `urgency`
- `message`
- `created_at`

### DeliveryAttempt

Stores:

- `id`
- `notification_id`
- `channel`
- `status` — `pending`, `sent`, `failed`, or `timeout`
- `attempted_at`

A unique constraint is applied to:

`(notification_id, channel)`

This prevents a previously recorded successful delivery from being sent again through the same channel.

### UserPreference

Stores:

- `user_id`
- `channel_priority`
- `quiet_hours`
- `opted_out_channels`

## Planned API

### `POST /notifications`

Submit a notification.

An optional client-supplied `dedup_key` can be used to prevent the same logical event from creating multiple notification records when the caller retries the request.

### `GET /notifications/{id}/status`

Returns the notification's delivery status and per-channel attempt history.

### `GET/PUT /users/{id}/preferences`

Retrieves or updates:

- Channel priority
- Quiet hours
- Opt-outs

## Pre-Dispatch Gating: Quiet Hours vs Urgency

Before starting the fallback sequence, the system checks whether the notification is urgent.

- **Urgent notification** → dispatch immediately.
- **Normal notification outside quiet hours** → dispatch normally.
- **Normal notification during quiet hours** → queue until the quiet-hours window ends.

Urgent/security notifications therefore bypass quiet hours completely.

## Channel Fallback & Timeout Strategy

The resolved channel order is based on the user's configured `channel_priority`, with opted-out channels removed. If no preference is configured, a system default order is used.

Each channel has a bounded timeout:

- Push — 3 seconds
- SMS — 8 seconds
- Email — 15 seconds

If a channel fails, returns an unsuccessful response, or times out, the attempt is marked accordingly and the dispatcher immediately moves to the next channel.

There is no open-ended retry loop against a single failed channel. This keeps the total fallback time bounded.

### Retry vs Fallback

Channel-level retry is intentionally disabled. A failed or timed-out channel is skipped and the dispatcher moves to the next available channel.

Separately, the application may retry its own processing after an internal error. Delivery-level deduplication prevents a previously recorded successful attempt from being sent again.

### Timeout and Unknown Delivery Outcome

A timeout represents an unknown delivery outcome. The provider may have accepted or even delivered the message before the application timed out.

Therefore, production provider integrations should use provider-supported idempotency keys so that retrying an ambiguous attempt does not create duplicate delivery.

## Idempotency & Deduplication

The design uses two layers of deduplication.

### 1. Submission-Level Idempotency

An optional client-supplied `dedup_key` on `POST /notifications` prevents the same logical event from creating multiple `Notification` records if the calling service retries its request after a network failure.

### 2. Delivery-Level Deduplication

Every delivery attempt is identified by:

`(notification_id, channel)`

This pair is enforced using a unique database constraint.

Before dispatching to a channel, the dispatcher checks whether a successful `DeliveryAttempt` already exists for that notification and channel. If one exists, the dispatcher skips the duplicate send and uses the existing result.

This provides at-least-once processing with database-level deduplication.

A true exactly-once guarantee cannot be provided across an external provider boundary using only a local database. If a provider accepts a message and the application crashes before recording the result, the delivery outcome is unknown. Provider-side idempotency support is therefore required for stronger production guarantees.

## Quiet Hours & Priority Handling

Quiet hours are checked once before the fallback sequence begins rather than being handled separately for every channel.

Urgent notifications skip the quiet-hours gate and are dispatched immediately.

Normal notifications occurring during quiet hours are queued and re-evaluated once the quiet-hours window closes.

## Escalation Path for Total Failure

If every available channel fails or times out, the notification's overall status becomes:

`all_channels_failed`

For urgent notifications, this additionally triggers an explicit escalation event.

The escalation is logged at `CRITICAL` severity to a separate escalation log/table, representing what could become an on-call page in a production system.

This ensures that a failed security notification is clearly distinguished from an ordinary notification that failed.

## Trade-offs

| Decision | Chosen Approach | Trade-off |
|---|---|---|
| Datastore | SQLite | Zero setup for a local demo. PostgreSQL would be more appropriate under real concurrent write load and multiple application instances. |
| Dispatch model | In-process asynchronous dispatch | Simple to reason about and test. Production could use a durable queue such as SQS or RabbitMQ to decouple API latency from channel latency. |
| Idempotency enforcement | Database unique constraint, single instance | Sufficient for the demo. A multi-instance deployment would require stronger distributed coordination and provider-side idempotency mechanisms. |
| Retry-before-fallback | None; fail fast to the next channel | Keeps fallback time bounded and predictable, but sacrifices tolerance for one-off transient failures on an otherwise healthy channel. |

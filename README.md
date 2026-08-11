# Multi-Channel Notification Delivery System

## Overview

A notification service that delivers a message to a user across one of several channels
(push, SMS, email — all mocked/logged for this exercise) with automatic fallback if the
primary channel fails, while preventing duplicate delivery through the same channel using
idempotency and deduplication and respecting user delivery preferences (channel priority,
quiet hours, opt-outs).

The core of this exercise isn't the channel integrations — it's the retry/fallback logic,
the idempotency guarantee, and the escalation path for total delivery failure.

## Assumptions

- **Channels are mocked.** Push, SMS, and email are simulated with a logged "send" call,
  artificial latency, and a configurable random failure rate. No real provider
  (Twilio, SES, FCM, etc.) is integrated.
- **Single-instance deployment.** The service runs as one process. Idempotency and
  deduplication are enforced via a single local datastore, not a distributed lock.
- **Two urgency levels only.** Every notification is either `urgent` or `normal`.
- **Per-channel timeout budgets are fixed.**
  - Push: 3 seconds
  - SMS: 8 seconds
  - Email: 15 seconds
- **Quiet hours are a single daily window per user**, stored as a fixed local offset.
- **The caller is trusted.** Authentication and authorization are out of scope for
  this exercise.

## Setup & Run Instructions

```bash
git clone https://github.com/aar-ess/multi-channel-notification-system
cd multi-channel-notification-system

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app --reload

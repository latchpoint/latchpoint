# ADR 0043: Notification Delivery Outbox + Retries

## Status
**Implemented**

## Context
Notifications are currently sent synchronously during rule action execution via `notifications.dispatcher.NotificationDispatcher.send()` (called from `backend/alarm/rules/action_executor.py`). This has a few architectural drawbacks:

- **Couples rule execution to external network IO** (timeouts, slow providers, HA downtime), increasing tail latency and failure blast radius.
- **No durable retry/backoff**: transient failures (timeouts/5xx/429) immediately fail the rule action with no automated retry.
- **Inconsistent behavior vs docs**: ADR 0036 describes retry logic, but the current implementation does not provide a shared, centralized retry policy.
- **Rate limits**: providers may return 429, requiring controlled retry scheduling and backoff to avoid amplifying failures.

Separately, ADR 0034 documents “notifications via `ha_call_service`”, while ADR 0035+0037 implement a dedicated notifications app and `send_notification` rule action. We should clarify the intended “default path” going forward.

## Decision

### 1) Standardize on `send_notification` for notifications
- Prefer `send_notification` for all notifications (including Home Assistant via the `home_assistant` handler / HA system provider).
- Keep `ha_call_service` for generic Home Assistant service calls, but treat it as **not the preferred notification path**.

### 2) Introduce a DB-backed outbox for delivery
Add a durable “delivery” record so notifications can be processed asynchronously and retried safely.

**New model**: `notifications.NotificationDelivery`
- Stores the intended notification payload (`provider_id` or HA system provider, `message`, `title`, `data`, `rule_name`).
- Tracks state: `pending`, `sending`, `sent`, `failed`, `dead`.
- Tracks retry metadata: `attempt_count`, `next_attempt_at`, `last_error_code`, `last_error_message`.
- Includes an `idempotency_key` (unique) to prevent duplicates when the same action is enqueued more than once.

**Idempotency key recommendation**
- Derive from stable inputs when available (e.g., `rule_id` + `provider_id` + canonicalized payload + a per-run/action GUID).
- When a rule action already has an internal log identifier, use it as part of the key so reprocessing/retries remain idempotent.

### 3) Execute `send_notification` by enqueueing (default)
Change the `send_notification` action execution path to:
- Validate the provider exists/enabled (or HA system provider has `data.service`).
- Create a `NotificationDelivery` (pending) and return success for “accepted/enqueued”.
- Do not perform network IO on the rule execution path by default.

**Exceptions**
- “Test provider” API remains synchronous (fast feedback), but may still write a log entry.

### 4) Add a scheduler task to process the outbox
Use the existing in-process scheduler (ADR 0024) to run a task such as `notifications_send_pending` every N seconds:
- Select due deliveries (`pending` and `next_attempt_at <= now`) with row-level locking to support concurrency.
- Dispatch via existing handlers.
- Write a `NotificationLog` per attempt (optionally link logs to deliveries).
- On success: mark delivery `sent`.
- On failure: compute `next_attempt_at` and either keep `pending` or mark `dead` when max attempts reached.

### 5) Centralize retry/backoff policy in one place
Define a single retry policy applied to all providers:
- **No retry**: authentication/permission failures (`AUTH_FAILED`, `FORBIDDEN`), invalid config, validation errors.
- **Retry**: timeouts, network errors, 5xx, and provider rate limiting (`RATE_LIMITED` / HTTP 429).
- Backoff: exponential with jitter (and `Retry-After` support where available), capped at a maximum delay.

## Alternatives Considered
- Keep synchronous sends in the rules engine: simplest, but makes rule evaluation less reliable and less responsive.
- Use Celery/Redis/RQ: robust, but adds operational complexity and extra infrastructure containers/services.
- Best-effort in-memory queue: simpler, but not durable across restarts and can drop notifications.

## Consequences
- Rule execution becomes faster and more resilient to provider outages, at the cost of eventual (not immediate) delivery.
- Adds one new table and a scheduler task; requires careful concurrency handling to avoid duplicate sends.
- Improves observability by separating “accepted” (enqueued) from “delivered” (sent).

## Todos
- Add `NotificationDelivery` model + migrations and wire it into `send_notification`.
- Implement `notifications_send_pending` scheduler task with row locking and backoff.
- Update UI to show delivery status and recent failures (optional).
- Update/clarify docs: ADR 0036 retry guidance should reference this centralized policy.

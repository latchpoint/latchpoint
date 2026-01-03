# ADR 0044: Notifications Architecture (Consolidated)

## Status
**Implemented**

## Context
Notifications evolved across multiple ADRs:

- ADR 0034 introduced notifications via `ha_call_service`.
- ADR 0035 proposed in-app notification providers and a dedicated `send_notification` action.
- ADR 0036 described Pushbullet as the first provider.
- ADR 0037 proposed a dedicated `notifications/` Django app layout.

The codebase now has a concrete implementation that differs from parts of those documents (provider coverage, delivery semantics, endpoint shapes). We need a single source of truth for “how notifications work today”.

## Decision

### 1) Notification configuration lives in the alarm system (per-profile)
- Notification providers are stored in `notifications.NotificationProvider` and scoped to the active `alarm.AlarmSettingsProfile`.
- Sensitive config fields are stored encrypted via `notifications.encryption.encrypt_config()` (built on `alarm.crypto` conventions).

### 2) Rules send notifications via a dedicated action: `send_notification`
- The rules engine supports a `send_notification` THEN action.
- Rule execution **enqueues** a durable `notifications.NotificationDelivery` outbox record and returns success/failure for “accepted for delivery”.
- Rule execution does not perform external network IO for notifications.

### 3) Home Assistant notifications are supported via a system provider
- When Home Assistant is configured, the UI exposes a virtual provider `ha-system-provider`.
- The selected HA `notify.*` service is provided in `send_notification.data.service`.

### 4) Delivery is asynchronous via the in-process scheduler (ADR 0024)
- A scheduled task processes due outbox records, sends them via provider handlers, logs attempts, and applies retry/backoff.
- Transient failures retry with exponential backoff + jitter up to a cap; non-retryable failures are marked dead.
- A lock timeout reclaims stuck “sending” deliveries on process crashes.

### 5) Synchronous send is reserved for tests/tools only
- The dispatcher has an internal “send now” method used by the outbox worker and “Test Provider” endpoint.
- Application flows should not call synchronous send directly.

## Implementation Notes

### Backend
- Models: `notifications.NotificationProvider`, `notifications.NotificationLog`, `notifications.NotificationDelivery`
- Dispatcher API: `NotificationDispatcher.enqueue(...)` and internal `_send_now(...)`
- Worker task: `notifications_send_pending` (scheduler-registered)

### Frontend
- Settings tab: “Notification Providers”
- Rule builder action: `send_notification` with provider selection and HA notify service picker for the HA system provider.

### Supported provider handlers (current)
- `pushbullet`, `discord`, `webhook`, `home_assistant`

## Alternatives Considered
- Keep notifications in HA only (`ha_call_service`): rejected due to UX and coupling to HA configuration.
- External worker (Celery/RQ): rejected due to additional infra/ops complexity for this project.
- In-memory queue only: rejected due to lack of durability across restarts.

## Consequences
- Notifications are resilient to transient provider failures and do not block rule execution.
- Delivery becomes eventually-consistent; logs/deliveries provide auditability.
- Provider coverage is intentionally incremental; additional providers can be added as handlers + UI forms.

## Todos
- Add additional provider handlers (Telegram/Pushover/Ntfy/Email/etc.) and corresponding UI forms.
- Optionally align provider-type metadata endpoint and frontend to be schema-driven.

# Additional Integrations Roadmap (Planning)

This document outlines a set of high-value “next integrations” for the alarm panel, with enough detail to scope work, align with existing architecture, and choose a phased delivery plan.

## Goals
- Expand the system beyond “arm/disarm + sensors” into **verification**, **notification**, **presence-aware automation**, and **operational reliability**.
- Keep the backend aligned with the existing integration decomposition:
  - Core domain depends on `backend/alarm/gateways/*` (not `backend/integrations_*` directly).
  - Settings live in the active `AlarmSettingsProfile` and secrets are encrypted at rest.
  - Tests must not hit external services by default; opt-in integration tests only.

## Non-goals
- Replacing Home Assistant as the primary device hub (HA remains the best place for device onboarding and local automation).
- Building a full video surveillance UI (we focus on “alarm verification” primitives: snapshots/clips/links).
- Creating a full monitoring-station product (we can design “bridges” and “exports” that support it later).

## Cross-cutting design decisions (recommended)
### 1) A unified “Notifications” capability
Most integrations below boil down to “emit a message when something happens”. A single internal interface avoids re-implementing rules, throttling, retries, templates, and audit logs per provider.

**Proposed abstraction**
- `backend/alarm/gateways/notifications.py`: `NotificationsGateway`
  - `send(channel, message, metadata)` (sync for MVP; async/retry later)
  - Channel examples: `sms`, `voice`, `push`, `telegram`, `email`, `webhook`
- `backend/integrations_notifications_*` provider apps implement the gateway (Twilio/Telegram/etc).

**Suggested persisted settings shape (per-provider)**
- `enabled` boolean
- provider credentials (encrypted where needed)
- routing configuration (e.g., recipients, phone numbers, chat ids)
- optional rate limiting / quiet hours

**Audit**
- `NotificationAttempt` model (or append-only event records) with provider response codes and error messages.

### 2) A “Verification” primitive
When the alarm triggers, users want immediate confidence: *what happened, where, and do I need to respond?*

**Proposed outputs**
- “Best available snapshot” (image URL + timestamp + camera name)
- Optional “clip link” (Frigate/NVR event URL)
- Optional “object detection label” (person/vehicle) and confidence

### 3) A “Presence” primitive
Geofence/presence inputs should normalize to a single concept: *who is home?* This unlocks safe auto-arming and reduces false alarms.

**Proposed outputs**
- Per-user presence: `home | away | unknown` with last update
- Household presence: derived `anyone_home` and “last left / first arrived”

### 4) Async + retries (later phase)
Initial integrations can run synchronously for a small installation, but network calls need a future path for:
- retries with backoff
- dead-letter handling
- idempotency keys (avoid duplicate SMS/push)

If/when added: introduce a lightweight background job runner (Celery/RQ/Channels task) without changing the public gateway API.

## Recommended delivery order (ROI first)
1) Notifications (one provider first, then expand)
2) Camera verification (Frigate first if present, otherwise generic RTSP snapshot via NVR)
3) Presence (HA presence entities first; optionally OwnTracks/Life360 later)
4) Ops/observability (Sentry + basic health endpoints)
5) Cloud backup/export (S3/GDrive optional)
6) Voice assistants + access control + monitoring bridges (more deployment-specific)

## Effort sizing (rough)
- **S (1–3 days)**: a single provider with basic settings + test button + minimal UI.
- **M (3–7 days)**: multiple endpoints, mapping UI, audit logs, and basic throttling.
- **L (1–3 weeks)**: async retries, multi-provider routing, complex mapping/automation, or external certification requirements.

---

## Integration 1: Notifications (SMS/Voice/Push/Chat/Email)

### Why it’s useful
- Fastest way to “complete” an alarm system: *know immediately* when the alarm triggers, arming starts, entry delay begins, or tamper is detected.

### Suggested MVP scope
- Start with **one provider** and one channel:
  - Twilio SMS *or* Telegram bot messages *or* Pushover.
- Send notifications for:
  - `alarm.triggered`
  - `alarm.arming_started` (optional)
  - `alarm.disarmed` (optional)
  - `code_failed_lockout` (security-relevant)
- Add basic throttling:
  - “no more than N messages per event type per X minutes”

### Backend design
- New gateway: `NotificationsGateway`
- Provider-specific apps:
  - `backend/integrations_twilio/` (SMS/voice)
  - `backend/integrations_telegram/` (bot token + chat ids)
  - `backend/integrations_pushover/` (user keys + app token)
  - `backend/integrations_email/` (SMTP config or SES)
- Settings:
  - Store credentials encrypted in the active profile.
  - Add an admin-only “Test notification” endpoint per provider.

### Proposed API endpoints (sketch)
- `GET/PATCH /api/alarm/notifications/settings/` (provider selection, routing, quiet hours)
- `POST /api/alarm/notifications/test/` (send test message to configured recipients)
- Provider-specific status (optional):
  - `GET /api/alarm/notifications/status/`

### Frontend UX
- Settings tab: “Notifications”
  - Provider selector + enable toggle
  - Credential fields (masked)
  - Recipient management
  - “Send test” button with clear success/failure UI

### Security notes
- Avoid exposing provider secrets in API responses (write-only secrets).
- Rate-limit “send test” endpoint.
- Consider a “panic/duress” path later that uses a separate high-priority routing.

### Testing strategy
- Unit test the gateway interface with a fake provider implementation.
- Provider integration tests opt-in via env (mirrors the HA opt-in testing approach).

---

## Integration 2: Cameras / NVR verification (Frigate-first)

### Why it’s useful
- The most effective false-alarm reducer: a snapshot/clip alongside the alert.

### Suggested MVP scope
- Support Frigate as the first-class source of truth for:
  - latest snapshot for a camera
  - recent events for a zone/time window
- Attach snapshot/clip links to `alarm.triggered` notifications.

### Effort
- **M** if Frigate API access is straightforward and mapping is manual.
- **L** if adding clip storage, multi-camera mapping automation, or rich UI playback.

### Backend design
- New gateway: `CamerasGateway` (or `VerificationMediaGateway`)
  - `get_snapshot(camera_id) -> {url|bytes, captured_at, source}`
  - `get_recent_event(camera_id, since) -> {event_id, url, label}`
- Provider apps:
  - `backend/integrations_frigate/`
  - (later) `backend/integrations_generic_nvr/` (RTSP snapshot via NVR endpoint)
- Settings:
  - base URL + auth token (encrypted) + camera mapping
  - optionally reuse HA entities as “camera registry” and store mapping in the profile

### Proposed API endpoints (sketch)
- `GET/PATCH /api/alarm/cameras/settings/` (provider, base URL, auth, camera mapping)
- `GET /api/alarm/cameras/status/`
- `POST /api/alarm/cameras/test/` (connection + list cameras)
- `GET /api/alarm/cameras/:camera_id/snapshot/` (returns link or proxied bytes)

### Frontend UX
- Settings tab: “Cameras / Verification”
  - Frigate connection settings + test
  - Camera mapping (choose from discovered HA camera entities or a manual list)
  - Preview snapshot button
- Alarm UI:
  - When triggered: show “Latest snapshot” panel with timestamp + source

### Open questions
- Do we store media (upload) or only link to it? (Recommend: **link only** for MVP.)
- How do we map sensors/zones to cameras? (Manual mapping first.)

---

## Integration 3: Duress PIN + monitoring/bridge options

### Why it’s useful
- A duress PIN enables “disarm but still alert” for personal safety.
- A monitoring bridge (webhook/contact ID) is the path to professional monitoring without rewriting the core.

### Suggested MVP scope (duress)
- Add a duress flag to the code validation flow:
  - A “duress code” disarms normally but emits a high-priority notification + event log entry.
- Add dedicated notification routing for duress (separate recipients).

### Effort
- **S/M** depending on how codes are modeled today and whether “duress” is per-code or per-user.

### Monitoring/bridge (later phase)
Options (choose one based on user demand):
- Webhook “alarm events” export (POST with signature)
- Contact ID (legacy) bridge via a small sidecar service

### Backend design notes
- Keep duress behavior in the **use case layer** (code validation / disarm use case), not the view.
- Emit an `AlarmEvent` entry for duress for audit and downstream integrations.

---

## Integration 4: Presence & geofencing (HA-first)

### Why it’s useful
- Enables safe auto-arming, auto-disarming, and “forgot to arm” reminders.

### Suggested MVP scope
- Treat Home Assistant as the primary presence source:
  - allow selecting HA entities (person/device_tracker) per user
  - compute `anyone_home`
- Use presence only for **recommendations and reminders** first:
  - “Everyone left, alarm is disarmed” → notify
  - “Someone arrived, alarm is armed away” → notify / suggest disarm

### Effort
- **M** (mapping UI + derived presence + reminders hooks).

### Backend design
- Gateway: `PresenceGateway`
  - `get_user_presence(user_id)` and `get_household_presence()`
- Store mapping from app user → HA presence entity in the active profile.
- Optional: periodic refresh (poll) plus event-driven updates (HA webhook/WS) later.

### Proposed API endpoints (sketch)
- `GET/PATCH /api/alarm/presence/settings/` (user↔entity mapping, toggles)
- `GET /api/alarm/presence/status/` (derived presence snapshot)
- `POST /api/alarm/presence/test/` (validate mapping and HA connectivity)

### Frontend UX
- Settings tab: “Presence”
  - map each user to HA presence entities
  - toggles for “remind to arm when everyone leaves”, “warn on arrival”

### Safety notes
- Default to “notify only” (no auto-disarm) until users explicitly enable automations.
- Require code for disarm even if presence says “home” (unless explicitly configured).

---

## Integration 5: Calendar-driven modes (vacation/guest windows)

### Why it’s useful
- Scheduled behavior without manual toggles: vacation mode, cleaning days, guest access windows.

### Suggested MVP scope
- Import a read-only calendar feed (ICS URL) and expose a “vacation active” boolean.
- Let rules/notifications reference this state (e.g., “extra notifications when vacation active”).

### Effort
- **S/M** for ICS fetch/parse + display; **L** if adding full scheduling and policy enforcement.

### Backend design
- Provider app: `backend/integrations_calendar_ics/`
- Settings: ICS URL (potentially secret), refresh interval, timezone
- Cache last fetch + last successful parse

### Proposed API endpoints (sketch)
- `GET/PATCH /api/alarm/calendar/settings/` (ICS URL, tz, refresh)
- `GET /api/alarm/calendar/status/` (last fetch time + parsed windows)
- `POST /api/alarm/calendar/test/` (fetch + parse + show sample)

### Frontend UX
- Settings tab: “Calendar”
  - add ICS URL + test parse
  - show upcoming “vacation” windows detected

---

## Integration 6: Access control ecosystems (deployment-specific)

### Why it’s useful
- Unifies “alarm state” with “door access events” and auditing.

### Suggested options (pick based on hardware)
- UniFi Access (events + door state)
- DoorBird / 2N (doorbell + call events)
- Generic webhook ingestion (for controllers that can POST events)

### MVP scope
- Start with **event ingestion** (read-only):
  - “door opened”, “badge used”, “door forced”
  - feed into `AlarmEvent` and optional notifications

### Effort
- **M/L** depending on vendor APIs and event models.

### Backend design
- Provider apps per ecosystem, but normalize into a single “access event” schema in core.
- Treat it like sensors: entity registry + mapping, not bespoke per device.

### Proposed API endpoints (sketch)
- `GET/PATCH /api/alarm/access/settings/` (provider config)
- `GET /api/alarm/access/status/`
- `POST /api/alarm/access/test/`
- `POST /api/alarm/access/events/ingest/` (signed webhook ingestion)

---

## Integration 7: Additional radio stacks (Zigbee2MQTT, Thread/Matter)

### Why it’s useful
- Expands sensor support and resilience; Zigbee sensors are common and cost-effective.

### Recommended approach
- Prefer integrating via Home Assistant when possible (keeps this app simpler).
- If direct integration is desired:
  - Zigbee2MQTT via MQTT discovery/topics (see ADR: `docs/adr/0049-zigbee2mqtt-entity-first-rules-driven-automation.md`)
  - Matter via HA (initially), with later direct support only if needed

### MVP scope (direct Zigbee2MQTT)
- Discover sensors and map them into the existing entity registry.
- Support basic binary sensors (contact/motion) first.

### Effort
- **M** for basic discovery + binary sensors; **L** for full device class coverage + OTA + rich metadata.

---

## Integration 8: Voice assistants (Alexa/Google)

### Why it’s useful
- Convenience for arming states and status, and for spoken alerts during entry/exit delay.

### MVP scope
- Start with Home Assistant voice integrations:
  - expose simple scripts/services in HA that call this app’s API
  - keep the “PIN required” flow in this app (avoid storing tokens in clients)

### Future scope
- Native Alexa Skill / Google Action:
  - requires a public endpoint and robust auth story; likely out of scope for local-first deployments

### Effort
- **S** if implemented via HA scripts/services; **L** for native Alexa/Google integrations.

---

## Integration 9: Ops/observability (Sentry/Prometheus/health)

### Why it’s useful
- Makes the system trustworthy: you know when it is down, disconnected, or misconfigured.

### Suggested MVP scope
- Add a `/api/health/` endpoint:
  - DB ok, WebSocket ok (optional), HA status, MQTT status
- Add structured logging for integration failures.

### Effort
- **S** for health endpoint + structured logs; **M/L** for full metrics + dashboards.

### Later scope
- Sentry for backend and frontend
- Prometheus metrics export and dashboards
- “Heartbeat” pings to Healthchecks.io (if desired)

---

## Integration 10: Backup/export/restore (profiles + critical data)

### Why it’s useful
- Protects from SD-card failure, DB corruption, or migration accidents.

### Suggested MVP scope
- Admin-only “Export configuration” (download JSON):
  - settings profiles (minus secrets unless user provides a passphrase)
  - sensors/entities mapping
  - rules
- Admin-only “Import configuration” with validation + preview.

### Effort
- **M** for export/import flows; **L** for scheduled cloud backups and encryption UX.

### Later scope
- S3/GDrive scheduled backups (requires async + secrets handling)
- Optional encryption with a user-provided passphrase

---

## Implementation checklist (per integration)
Use this checklist to keep new integrations consistent:

1) Add/extend a `backend/alarm/gateways/*` interface (core depends on this only).
2) Implement provider app under `backend/integrations_*` with:
   - settings schema stored in profile (+ encrypted secrets)
   - status endpoint
   - test endpoint (admin-only)
3) Wire settings application on startup (existing `apply_integration_settings` flow).
4) Add DRF endpoints using thin views + a use case.
5) Add frontend settings tab/page that matches the “per-tab save” UX.
6) Add unit tests with fake providers; gate real network tests behind explicit env vars.

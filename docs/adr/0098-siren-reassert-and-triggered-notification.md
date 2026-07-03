# ADR-0098: Siren Re-Assert While Triggered + Built-In Triggered Notification

**Status:** Accepted
**Date:** 2026-07-02
**Author:** Leonardo Merza

## Context

### Incident (2026-07-01, prod)

The back door opened at 21:02:08 EDT while `armed_night`; the 60 s entry delay expired
undisarmed and the alarm went `triggered` at 21:03:10. The [ADR-0097](0097-ring-keypad-v2-burglar-siren-timeout.md)
fix (#73) was deployed and **worked**: the keypad ACKed the burglar-siren command (HA recorder
shows `Alarming: Burglar – Timeout: Seconds` flip 0→240 at 21:03:10.9, sound level 50). But:

1. The siren is a **one-shot** Indicator CC timeout, capped at 255 s and only re-sent on
   `alarm_state_change_committed` — so it went silent at ~21:07 while the alarm stayed
   `triggered` until the keypad disarm at 00:02:56 (~2 h 56 m triggered-and-silent). This is
   exactly the ADR-0097 risk-table entry "Siren auto-stops after ~4 min… revisit Option C".
2. **No notification was sent at any point** — `notifications_notificationdelivery` has zero
   rows for the window. The only trigger-path rule action is `alarm_trigger`; there is no
   built-in notify-on-triggered hook, so a triggered alarm can go unnoticed for hours.

## Decision

### 1. Periodic siren re-assert with a bell cutoff (ADR-0097 Option C)

A scheduler task `resync_ring_keypad_siren` (`backend/control_panels/tasks.py`,
`Every(seconds=120)`) re-runs `sync_ring_keypad_v2_devices_state()` while the alarm state is
`TRIGGERED`, which re-writes the burglar indicator (volume + `key 6 = 0` + `key 7 = 240`) and
restarts the tone before the previous 240 s write expires (120 < 240 → continuous sound).

- **Bell cutoff:** re-sends stop once the latest `AlarmEvent(event_type=triggered)` is older
  than `_BURGLAR_SIREN_MAX_TOTAL_SECONDS = 900` (15 min — a typical bell-cutoff duration;
  prod has no triggered auto-clear, so an uncapped siren could run for hours). The final
  re-send plays out, so the effective ceiling is ~cap + one tone duration (~19 min worst case).
- **Teardown is free:** leaving `triggered` re-syncs the keypad to a mode indicator via the
  existing state-change signal, silencing the tone early — the task itself never needs to stop it.
- The task no-ops on a cheap snapshot read in every other state.

Rejected alternatives (from ADR-0097): a longer one-shot via `key 6` minutes (still lost if the
single write is dropped, and 255 min max invites a runaway); keeping the 4-min cap (this incident
shows it silently under-serves the actual failure mode — nobody home to hear the first 4 minutes).

### 2. Built-in notification on transition into `triggered`

A receiver in `backend/notifications/receivers.py` on `alarm.signals.alarm_state_change_committed`
(`state_to == TRIGGERED`) enqueues a delivery to **every enabled `NotificationProvider` of the
active profile** via the durable outbox (drained by `notifications_send_pending`). It fires at
the real trigger moment independent of rule configuration — a `send_notification` rule action on
the trigger rule would fire at entry-delay start (`pending`) instead, and also on every
false-start that gets disarmed in time.

The `ha-system-provider` pseudo-provider is **not** included: it requires an explicit
`data["service"]` and there is no configured default HA notify service to send to. Operators
who want HA notifications add a Home Assistant provider in the UI like any other.

## Consequences

### Positive
- A triggered alarm now sounds for up to 15 minutes (vs 4) and survives a lost re-send
  (next tick repairs it), and every enabled provider is notified at trigger time.
- No new silencing path: teardown reuses the existing state-change sync.

### Negative / Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Re-write restarts rather than extends the tone on some firmware (brief gap/stutter every 120 s). | Low | Low | Verified pattern matches the entry/exit-delay tones; live test-fire on deploy. |
| No enabled providers configured (prod today) → notification hook is a no-op. | Certain until configured | Medium | Receiver logs a warning; operator must add a provider in the UI. |
| Scheduler down → no re-assert. | Low | Low | First 240 s tone still fires via the signal path; scheduler health is already monitored. |

### Neutral
- Prod must be redeployed to a `:main` build containing this change, and at least one
  notification provider must be created in the UI for the notify hook to do anything.

## Implementation

1. `backend/control_panels/zwave_ring_keypad_v2.py` — `_BURGLAR_SIREN_MAX_TOTAL_SECONDS = 900`.
2. `backend/control_panels/tasks.py` (new) — `resync_ring_keypad_siren` task; registered via
   `control_panels/apps.py` ready-time import.
3. `backend/notifications/receivers.py` (new) — `notify_on_alarm_triggered`; wired in
   `notifications/apps.py`.
4. Tests: `backend/control_panels/tests/test_tasks.py`,
   `backend/notifications/tests/test_alarm_triggered_notification.py`.

## Related

- [ADR-0097](0097-ring-keypad-v2-burglar-siren-timeout.md) — the one-shot siren fix this extends (its Option C).
- [ADR-0096](0096-scheduled-alarm-timer-ticker.md) — established the scheduler as the safety net for time-driven alarm behavior.
- [ADR-0091](0091-rule-action-entry-delay.md) — entry-delay deferral that produced the `pending` window in this incident.

# ADR-0097: Ring Keypad v2 Burglar Siren via Non-Zero Indicator CC Timeout

**Status:** Accepted
**Date:** 2026-06-27
**Author:** Leonardo Merza

## Context

### Background

When the alarm reaches `triggered`, the Ring Keypad v2 ("Back Door Keypad", Z-Wave node 13)
is supposed to sound its burglar siren. On 2026-06-27 the alarm triggered
(`armed_night → pending → triggered`, `timer_expired`) but the keypad stayed **silent**.

The siren is driven over the Z-Wave **Indicator Command Class (CC 135)**. The keypad re-syncs
its indicators only on the `alarm_state_change_committed` signal
(`backend/control_panels/runtime.py:52-65`) — there is **no periodic re-sync**.

### Current State (the bug)

`_sync_device_state()` `TRIGGERED` branch (`backend/control_panels/zwave_ring_keypad_v2.py:347-360`)
writes to the burglar indicator (property 13):

```
property_key 9 (Sound level) = beep_volume   # supported
property_key 6 (Timeout: Minutes) = 0
property_key 7 (Timeout: Seconds) = 0         # ← "sound for 0 seconds" = SILENT
property_key 1 (Multilevel) = 99              # indicator 13 doesn't support key 1 → ignored
```

Per the zwave-js Indicator registry, property_key 7 is **"Timeout: Seconds"** — the duration the
indicator stays on. The alarm indicators (12 "Alarming", 13 "Alarming: Burglar") are activated by
a **non-zero timeout**, exactly like the working entry/exit-delay tones
(`zwave_ring_keypad_v2.py:336,345` use `property_key 7 = seconds`). Setting the timeout to `0`
plays the tone for zero seconds.

PR #64 (`3b7b9bd`) introduced the zeroing on the inverted assumption that the timeout was a
~5 s "auto-clear" suppressing a sustained siren, so it zeroed the timeout and drove the
(unsupported) multilevel `key 1 = 99` to "hold" the siren. PR #69 (`9e2828a`) only added
failure logging ("burglar siren commanded") and explicitly deferred root cause to "a live
test-fire" — and prod runs the `:main` image from 2026-06-11, which predates even that logging.

### Confirmation (live test-fire, 2026-06-27)

The known-good Home Assistant command that sounded the siren before Latchpoint existed:
`zwave_js.set_value {command_class:135, property:13, property_key:7, value:5}` → 5-second
burglar tone. Replayed via HA against node 13 — **the keypad sounded.** The cached node
interview confirms indicator 13 honors timeout writes and that the deployed state
(`property 7 = 0`) sits silent.

### Requirements

- On `triggered`, the keypad must **audibly** sound the burglar tone.
- Disarm (and any subsequent state change) must **silence** it.
- No regression to the arm/disarm/entry-delay/exit-delay indicator paths.
- Siren duration must be **bounded** (noise courtesy / safety) and not depend on infra we don't have.

### Constraints

- Keypad indicator sync is **event-driven only** (`alarm_state_change_committed`); nothing
  re-syncs mid-`triggered`, so a single command must carry the full intended duration.
- The Indicator CC timeout is one byte per unit: `property_key 7` (seconds) ≤ 255 (~4 min),
  `property_key 6` (minutes) ≤ 255 (~4 h). There is **no "sound forever" value.**
- `alarm/rules/` and `alarm/use_cases/` must not import integrations; the keypad sync already
  lives in `control_panels` and listens to an alarm signal, which is allowed.

## Decision

**Chosen option: A — bounded siren via a non-zero `property_key 7` (seconds).**

In `_sync_device_state()` `TRIGGERED` branch, mirror the proven entry/exit-delay pattern:

1. Set volume `property_key 9` from `beep_volume` (unchanged).
2. Set `property_key 6` (minutes) = `0` and `property_key 7` (seconds) = **`_BURGLAR_SIREN_SECONDS = 240`** — a positive, bounded duration (≤255 s cap).
3. **Remove** the unsupported `property_key 1 = 99` write.
4. Rewrite the inverted comment.

Disarm continues to silence the siren early: the `DISARMED` branch selects the disarmed-mode
indicator (`zwave_ring_keypad_v2.py:317`), and Ring stops the alarm tone when another mode is
selected. 240 s is "until disarm" in practice while bounding the worst case to ~4 minutes.

## Alternatives Considered

### Option A — bounded timeout via `property_key 7` (seconds) *(chosen)*
- **Pros:** uses the exact mechanism verified on hardware; mirrors the existing, working
  entry/exit-delay code; ~3-line change; auto-stops responsibly; disarm cuts it off early.
- **Cons:** capped at ~4 min, so not literally indefinite if the user never disarms.

### Option B — `property_key 6` (minutes) for a multi-minute/hour hold
- **Pros:** longer single-command duration (up to ~4 h).
- **Cons:** the minutes property was **not** proven on hardware (test stopped before that step);
  a 4 h runaway if never disarmed is undesirable.

### Option C — true until-disarm via a periodic scheduler re-send
- **Pros:** genuinely sounds until disarm with no cap; most faithful to the original intent.
- **Cons:** requires a recurring task that re-arms a short timeout while `triggered` plus
  teardown — meaningful new infra/coupling for a rare state. Could build on the
  [ADR-0096](0096-scheduled-alarm-timer-ticker.md) 1 s ticker later if a hard cap proves too short.

## Consequences

### Positive
- The burglar siren actually sounds on `triggered`, fixing a safety-critical gap that has been
  latent since #64.
- Minimal, low-risk change reusing a verified code pattern; arm/disarm/delay paths untouched.
- `log_failures=True` (from #69) stays, so a future dropped write is diagnosable.

### Negative / Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Siren auto-stops after ~4 min if no one disarms. | Medium | Low | Acceptable as a bell cutoff; revisit Option C if a longer/indefinite siren is wanted. |
| Keypad asleep/unreachable when commanded. | Low | Medium | Node is FLiRS and reachable in practice; `log_failures=True` surfaces failed writes. |
| Stale `property_key 6` minutes value extends duration. | Low | Low | Branch explicitly writes `key 6 = 0` alongside `key 7`. |

### Neutral
- Prod must be redeployed to a `:main` build that includes both #69 (logging) and this fix.

## Implementation Plan

1. `backend/control_panels/zwave_ring_keypad_v2.py`: add `_BURGLAR_SIREN_SECONDS = 240`; in the
   `TRIGGERED` branch write `key 6 = 0` and `key 7 = _BURGLAR_SIREN_SECONDS`, drop the `key 1`
   write, fix the comment.
2. `backend/control_panels/tests/test_ring_keypad_v2.py`: update
   `test_sync_triggered_sounds_sustained_burglar_siren` to assert a non-zero `key 7` and the
   **absence** of a `key 1` write on indicator 13.
3. `uvx ruff check backend/` + `uvx ruff format --check backend/`;
   `python manage.py test control_panels`.
4. Deploy current `:main` to prod and verify a real trigger sounds the keypad until disarm.

## Acceptance Criteria

- [ ] **AC-1**: When the alarm enters `triggered`, `_sync_device_state()` issues an Indicator CC (135) write to property 13 with `property_key 7` set to a **positive** value.
- [ ] **AC-2**: The `TRIGGERED` branch issues **no** write with `property_key 7 = 0` (nor `6` as the sole non-zero with `7 = 0`).
- [ ] **AC-3**: The `TRIGGERED` branch issues **no** `property_key 1` write to property 13.
- [ ] **AC-4**: Volume (`property_key 9`) is still set from `beep_volume` on trigger.
- [ ] **AC-5**: The disarm/arm/entry-delay/exit-delay indicator paths are unchanged (their tests still pass).
- [ ] **AC-6**: `python manage.py test control_panels` passes and `uvx ruff check/format` are clean.

## Related ADRs

- [ADR-0091](0091-rule-action-entry-delay.md) — keypad entry-delay tone; same volume + `property_key 7` (seconds) pattern this fix mirrors.
- [ADR-0096](0096-scheduled-alarm-timer-ticker.md) — the 1 s scheduled ticker that Option C would build on for an indefinite siren.
- [ADR-0092](0092-zwavejs-lock-push-sync.md) — related Z-Wave JS push-sync from alarm state.

## References

- `backend/control_panels/zwave_ring_keypad_v2.py:347-360` — `TRIGGERED` branch (fixed).
- `backend/control_panels/zwave_ring_keypad_v2.py:336,345` — working entry/exit-delay timeout pattern.
- zwave-js `@zwave-js/core` Indicator registry — `property_key 7 = "Timeout: Seconds"`, `9 = "Sound level"`; Indicator `0x0c`=Alarming, `0x0d`=Alarming: Burglar.
- Known-good HA command: `zwave_js.set_value {cc:135, property:13, property_key:7, value:5}`.
- PRs #64 (`3b7b9bd`, inverted timeout), #69 (`9e2828a`, logging only).

## Todos

- Consider Option C (periodic re-send) if a >4 min / indefinite siren is desired.

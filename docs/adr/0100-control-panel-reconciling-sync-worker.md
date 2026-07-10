# ADR-0100: Reconciling Panel-Sync Worker (Alarm State ↔ Control Panel, Both Directions)

**Status:** Accepted
**Date:** 2026-07-10
**Author:** Leonardo Merza

## Context

### Incident (2026-07-10, prod, first boot of the ADR-0099 build)

Two symptoms, reproduced live this morning:

1. **Arming from the app sounded the full burglar siren immediately.** Arm committed at
   ~11:26:21 EDT; HA recorder shows the burglar `Timeout: Seconds` register flip **240 → 0 at
   11:26:21** — the ADR-0099 "teardown clear" — and the keypad started the siren at that instant.
2. **Keypad disarm-code entry was very slow to take effect.** The disarm code was typed during
   the arming window; the keypad kept sounding for ~15+ more seconds. The HA mirror shows
   `arming` published at 11:26:41 (~19 s after the DB transition) and `disarmed` at 11:27:02.

Prod log correlation for the same window (`docker logs docker-latchpoint-1`):
`Ring Keypad v2 sync: alarm_state=arming` at ~11:26:22 → HA MQTT publish of `arming` at 11:26:41
→ `Ring Keypad v2 sync: alarm_state=disarmed` at ~11:26:44 → HA publish `disarmed` at 11:27:02.
The keypad sync writes consumed ~19 s and ~18 s respectively, and everything else queued behind them.

### Root cause A — blocking device I/O inside post-commit signal receivers

Every state change fires `alarm_state_change_committed` (post-commit,
`alarm/state_machine/snapshot_store.py:87-91`); receivers run **serially on the committing
thread**. The control_panels receiver ran `sync_ring_keypad_v2_devices_state()` inline, and each
Indicator CC write is a **supervised Z-Wave round-trip with a 10 s timeout**
(`integrations_zwavejs/manager.py` — `async_set_value(..., wait_for_result=True)`,
`set_value(timeout_seconds=10.0)`). Consequences:

- App arm/disarm HTTP requests blocked ~20 s (Django runs `on_commit` callbacks inside the request).
- Receiver order is INSTALLED_APPS order (`alarm` → `control_panels` →
  `integrations_home_assistant`), so the WS broadcast ran first but the **HA MQTT mirror queued
  behind the keypad writes** — mirror timestamps stopped equaling DB transition times.

### Root cause B — the single inbound Z-Wave event thread also performed outbound feedback

ALL inbound Z-Wave events funnel through a **1-worker** executor
(`integrations_zwavejs/manager.py:214`, `zwavejs-events`). When a transition commits on that
thread (keypad-initiated arm/disarm), its post-commit keypad sync **blocked the same thread**,
so the next keypad event (the user's disarm code) sat in queue behind the previous transition's
feedback writes. The inbound handler also performed blocking "code not accepted" indicator
writes inline. The panel's feedback loop starved its own command channel.

### Root cause C — write-only, edge-sensitive device protocol built on an unverified semantic model

The driver never read or tracked the keypad's indicator registers; three ADRs in a row patched
symptoms while guessing the activation semantics:

- ADR-0097 assumed `Timeout: Seconds = 0` means "sound for 0 s" (silent).
- ADR-0099 assumed activation is a rising edge `0 → non-zero` and added a **teardown clear
  (write 0) on every non-triggered sync**.

All hardware observations to date fit a simpler, different model:

> **Any value-CHANGING write to the burglar timeout register (indicator 13, property_key 7)
> activates the siren** (with the written value as the auto-stop timeout; `0` = no auto-stop).
> **Writing the register's current value does nothing.** Selecting a mode indicator silences
> the tone.

| Date | Write | Register | Result | Consistent |
|---|---|---|---|---|
| 2026-07-01 | 240 | 0 → 240 | siren sounded | ✔ |
| 2026-07-07 / 07-09 | 240 | 240 → 240 | silent (the ADR-0099 incident) | ✔ |
| 2026-06-27 (#64 code) | 0 | 0 → 0 | silent | ✔ |
| **2026-07-10 11:26:21** | **0 (teardown clear)** | **240 → 0** | **siren sounded on arm** | ✔ |

The ADR-0099 teardown clear is therefore itself the arm-sounds-siren regression: the first
non-triggered sync after any trigger performs a value-changing write to the register.

## Decision

Replace inline signal-driven device I/O with a **reconciling panel-sync worker**
(`backend/control_panels/sync_worker.py`), the single owner of all panel Indicator CC writes:

1. **Non-blocking producers.** The `alarm_state_change_committed` receiver, the ADR-0098
   `resync_ring_keypad_siren` task, and the inbound keypad handler's feedback tones only
   enqueue work (`request_sync` / `request_siren_reassert` / `request_code_rejected`) and
   return immediately. No thread that commits transitions or receives Z-Wave events ever
   performs a supervised write again.
2. **Coalescing.** The worker reconciles against the **latest** alarm snapshot; a burst of
   transitions results in one sync. A sync that fails is retried (3 attempts, 1 s backoff)
   unless a newer state supersedes it.
3. **Tracked registers (desired-state diffing).** Each successful write is recorded in a new
   `ControlPanelDevice.last_written_indicators` JSON field (keys `"property:key"`, plus
   `"mode"` and `"state"`). Syncs compute desired writes as a **pure function**
   (`_desired_indicator_writes`) and only write diffs:
   - **Burglar register (13:7) is written ONLY while TRIGGERED.** Sounding the siren = writing
     whichever of 240/239 differs from the last written value (a guaranteed value change).
     With no tracked value (fresh install, pre-0100 rows) the trigger path writes `0` then
     `240` — both orderings sound the siren regardless of the physical register.
   - The ADR-0098 re-assert goes through the same path, so each re-assert is a genuine
     value change (fixing the silent-re-assert flaw ADR-0099 identified but did not fix).
   - Silencing remains mode-indicator selection (proven on hardware); the mode write is forced
     whenever the alarm state changed, even if the same mode indicator was selected before an
     intervening trigger.
   - Volume/minutes writes are diffed; entry/exit countdown seconds are always written
     (the device decrements them to 0 on its own) and never tracked.
4. **Failure semantics.** A failed write leaves the tracked state unchanged (the next sync
   retries it), records `device.last_error`, and keeps the greppable
   `"burglar siren commanded"` / `"indicator write failed"` log lines.

### Hardware verification (pre-deploy validation)

The corrected semantic model explains all six observations but was inferred, not bench-tested.
Before (or at) deploy, verify on node 13 via HA `zwave_js.set_value` (each step may sound the
siren briefly — coordinate the window):

1. register 0 → write 0 → expect silent
2. register 0 → write 5 → expect 5 s siren
3. register 5 → write 5 → expect silent (same-value no-op)
4. register 5 → write 4 → expect siren (any value change activates)
5. while sounding → select Disarmed (indicator 2, key 1 = 99) → expect silence; note whether
   the register self-resets
6. register non-zero, silent → select mode, then write the same register value → expect silent

If a step contradicts the model, only `_desired_indicator_writes` needs adjusting — the worker
architecture is policy-agnostic.

## Alternatives Considered

### Scheduler-based reconciler
Same diffing logic driven by a fast (~1-2 s) scheduler task (ADR-0096 pattern) with receivers
setting a dirty flag. Rejected: adds up to one tick of feedback latency, and a slow write
(10 s timeout) stalls the shared scheduler thread's other tasks.

### Minimal async dispatch
Fire a one-shot thread per state change running the old sync logic. Rejected: fixes only the
latency symptom; concurrent syncs can interleave writes to the same device, and the ADR-0099
class of register-semantics bugs (including the 7/10 regression) remains.

## Consequences

### Positive
- Arm/disarm from app, keypad, HA, and rules commit and confirm in milliseconds; keypad
  feedback happens within one write round-trip instead of queueing behind unrelated writes.
- The HA mirror and WS broadcasts publish immediately again (mirror timestamps == DB times).
- The siren sounds on **every** trigger and re-assert (guaranteed value-changing writes), and
  never outside TRIGGERED (register untouched in all other states).
- The single-writer worker eliminates interleaved writes from HTTP/scheduler/event threads.

### Negative / Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Semantic model still wrong in some corner (e.g. mode-select resets the register) | Low | Medium | Hardware test matrix above; policy isolated in one pure function; tracked values make any fix local. |
| Tracked register drifts from device (external writes via HA/zwave-js) | Low | Low | Reassert alternation still changes value unless externally set to the exact alternate; next trigger self-corrects. |
| Worker thread dies | Low | Medium | Thread is daemon + top-level exception guard per drain; a dead worker leaves indicators stale but never blocks alarm transitions. |
| Sync no longer runs inline in tests that relied on it | Certain | Low | Tests drain the worker explicitly; `sync_ring_keypad_v2_devices_state()` remains directly callable. |

### Neutral
- `last_written_indicators` is internal (not exposed via the device serializer).
- Prod must be redeployed; the first post-deploy trigger uses the unknown-register
  reset-then-set path once, then tracking takes over.

## Implementation

1. `backend/control_panels/sync_worker.py` (new) — `PanelSyncWorker` + `panel_sync_worker`.
2. `backend/control_panels/zwave_ring_keypad_v2.py` — `IndicatorWrite`, pure
   `_desired_indicator_writes`, reconciling `_sync_device_state`, `play_code_rejected`,
   `_request_code_rejected`; teardown clear and unconditional reset-then-set removed.
3. `backend/control_panels/runtime.py` — receiver enqueues; worker started in `initialize()`.
4. `backend/control_panels/tasks.py` — re-assert task calls `request_siren_reassert()`.
5. `backend/control_panels/models.py` + migration 0004 — `last_written_indicators`.
6. Tests: `tests/test_sync_worker.py` (new); policy/reconciliation tests and inverted
   non-triggered invariant in `tests/test_ring_keypad_v2.py`; worker-mock updates in
   `tests/test_tasks.py`, drain calls in `tests/test_ring_keypad_v2_rearm.py`.

## Related ADRs

- [ADR-0097](0097-ring-keypad-v2-burglar-siren-timeout.md) — superseded semantic model ("0 = silent").
- [ADR-0098](0098-siren-reassert-and-triggered-notification.md) — re-assert task retained; its writes now guaranteed value-changing.
- [ADR-0099](0099-burglar-siren-rising-edge-activation.md) — superseded: the teardown clear it introduced caused the 2026-07-10 arm-sounds-siren regression; its reset-then-set survives only as the unknown-register trigger path.
- [ADR-0096](0096-scheduled-alarm-timer-ticker.md) — the scheduler pattern considered and rejected for panel I/O.

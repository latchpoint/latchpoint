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

The corrected model — initially inferred from prod evidence, then **live-verified on the
device the same day** (see Hardware verification below):

> **A write of `0` to the burglar timeout register (indicator 13, property_key 7) ALWAYS
> sounds the siren with no auto-stop — even over an already-0 register.** A write of a
> non-zero value over a different register value sounds it for that many seconds (duration is
> honored). **Writing the same NON-ZERO value as the register is a device no-op.** Selecting
> a mode indicator silences the tone; the register does NOT self-reset.

| Date | Write | Register | Result | Verdict |
|---|---|---|---|---|
| 2026-07-01 | 240 | 0 → 240 | siren, auto-stop at ~240 s | ✔ activation + duration honored |
| 2026-07-07 / 07-09 | 240 | 240 → 240 | silent (the ADR-0099 incident) | ✔ same non-zero value = no-op |
| 2026-06-27 (#64 code) | 0 | 0 → 0 | silent | ⚠ unreliable — image predates write-failure logging; delivery unconfirmed |
| **2026-07-10 11:26:21** | **0 (teardown clear)** | **240 → 0** | **siren sounded on arm** | ✔ 0-write activates |
| 2026-07-10 live test | 0 | 0 → 0 | **siren, no auto-stop** | ✔ 0-write activates even over 0 |

The ADR-0099 teardown clear is therefore itself the arm-sounds-siren regression — and worse
than first thought: because a 0-write activates even over an already-0 register, the deployed
build sounds the siren on **every** state-change sync, with nothing to cut it off in the
`arming`/`pending` branches (no mode-select there). Both 7/10 arm tests sounding is explained.

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
   - **Burglar register (13:7) is written ONLY while TRIGGERED.** Sounding the siren always
     uses reset-then-set (`0`, then `240`): a 0-write is hardware-verified to ALWAYS activate
     — even over an already-0 register — and `0 → 240` is a verified activator, so the
     sequence sounds regardless of what the register holds, with no dependence on
     same-value/dedupe semantics. (An earlier draft used 240/239 alternation; dropped because
     it depended on "any value change activates", which the live test did not confirm.)
   - The ADR-0098 re-assert goes through the same path, so each re-assert genuinely restarts
     the tone (fixing the silent-re-assert flaw ADR-0099 identified but did not fix).
   - Silencing remains mode-indicator selection (proven on hardware); the mode write is forced
     whenever the alarm state changed, even if the same mode indicator was selected before an
     intervening trigger.
   - Volume/minutes writes are diffed; entry/exit countdown seconds are always written
     (the device decrements them to 0 on its own) and never tracked.
4. **Failure semantics.** A failed write leaves the tracked state unchanged (the next sync
   retries it), records `device.last_error`, and keeps the greppable
   `"burglar siren commanded"` / `"indicator write failed"` log lines.

### Hardware verification (run live 2026-07-10, ~15:28–15:35 EDT, node 13)

Executed via HA `zwave_js.set_value` with the user listening; register transitions confirmed
through the HA recorder (`number.back_door_keypad_alarming_burglar_timeout_seconds`):

| Step | Write (register before) | Result | Verdict |
|---|---|---|---|
| 0-over-0 | 13:7 = 0 (register 0) | **SIREN, no auto-stop** (user-confirmed on re-run) | ❌ refuted "same-value = no-op" for zero: **a 0-write ALWAYS activates** |
| 0 → 5 | 13:7 = 5 | write ACKed 15:28:36; tone activation consistent with 6/27 manual 5 s test | ✔ non-zero write over different value activates, duration honored |
| 240-over-240 | (prod 7/7 + 7/9) | silent | ✔ same NON-ZERO value = device no-op |
| mode-select while sounding | 2:1 = 99 | silences immediately; **register stays at written value (240 observed), no self-reset** | ✔ silencer confirmed; stuck-register mechanism confirmed |
| 240 → 0 | 13:7 = 0 | siren starts (deliberate reproduction of the 7/10 arm regression) | ✔ teardown-clear regression confirmed live |

Consequences applied to the policy: the 240/239 single-write alternation was **dropped** —
every siren activation now uses reset-then-set (`0` then `240`), which rests only on verified
facts. The 6/27 "write 0 over 0 was silent" observation from the #64 era is reclassified as
unreliable (that prod image predates write-failure logging; delivery was never confirmed).
The always-activating 0-write also means the deployed ADR-0099 build sounds the siren on
EVERY state-change sync (its teardown clear), not just after a trigger — arming/pending syncs
have no subsequent mode-select to cut it off, which is exactly the user's 7/10 experience on
both arm tests.

**Community-doc comparison** ([ImSorryButWho's RingKeypadV2 notes](https://github.com/ImSorryButWho/HomeAssistantNotes/blob/main/RingKeypadV2.md)):
aligns on the mode/delay/sound property map and on the alarm indicators playing "until another
mode is selected" (our latched-register finding). It diverges on activation: it drives alarms
via `property_key 1` and claims alarm properties "do not respect duration (property_key 7)" —
but this unit demonstrably honors key-7 durations (6/27 manual 5 s test, 7/1 auto-stop at
exactly 240 s in the recorder). Likely a firmware difference. We deliberately do NOT use the
key-1 activation: if it latches until mode-select ignoring duration, the ADR-0098 15-minute
bell cutoff would be unenforceable device-side.

Residual risk of reset-then-set: if the `0` lands but the `240` write fails, the siren sounds
with no auto-stop until a mode-select (i.e. disarm) or a successful retry — acceptable while
TRIGGERED (the worker retries, and the 120 s re-assert task provides further repair windows).

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
| Tracked register drifts from device (external writes via HA/zwave-js) | Low | Low | Siren activation is reset-then-set (0 then 240) and a 0-write always activates, so drift cannot silence a trigger; drift only affects diff-only skips of volume/minutes. |
| Reset-then-set: `0` lands but `240` write fails → siren latched with no auto-stop | Low | Low | Only reachable while TRIGGERED (sound is desired); worker retries + 120 s re-assert repair it, and any disarm/mode-select silences. |
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

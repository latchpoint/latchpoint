# ADR-0104: Burglar Siren Sounds Continuously Until Disarmed

**Status:** Accepted
**Date:** 2026-07-24
**Author:** Leonardo Merza

**Amends:** ADR-0100 (reset-then-set activation)
**Supersedes:** ADR-0098 (bell cutoff), ADR-0097 (240 s tone duration)

## Context

### Incident (2026-07-24, prod, `:main`)

The alarm triggered and the keypad siren sounded for a split second. Device-side ground truth
from the HA recorder (`number.back_door_keypad_alarming_burglar_*`) and prod container logs:

| Time (EDT) | Event |
|---|---|
| 21:15:34.872 | `pending` (entry delay) |
| 21:16:35.103 | **`triggered`** |
| 21:16:35.771 | `13:7` → **0**  ← siren starts |
| 21:16:35.955 | `13:7` → **240**  (**184 ms** later) |
| 21:16:46.751 | `13:7` → **0** (120 s watchdog re-assert) |
| 21:16:46.935 | `13:7` → **240** (**184 ms** later) |
| 21:16:54.685 | `disarmed` |

Every write landed — supervised, ACKed, no `indicator write failed` lines. Nothing else touched
the keypad in that window: no mode-select, no code-rejected tone, no entry/exit-delay write. The
184 ms gap is identical on both attempts because it is simply the Z-Wave round-trip time.

This is the eighth siren defect and the seventh fix attempt (PRs #64, #68, #69, #73/ADR-0097,
#74/ADR-0098, #75/ADR-0099, #76/ADR-0100).

### Root cause: a composition failure, not a semantics failure

ADR-0100's hardware test matrix (2026-07-10) verified four sequences **individually**:

| Sequence | Result |
|---|---|
| `0-over-0` | siren, no auto-stop |
| `240-over-240` | silent (same non-zero value = device no-op) |
| `240 → 0` | siren starts |
| mode-select while sounding | silences immediately |

It then shipped a **fifth** that was never tested: `0` immediately followed by `240`. The
"`0 → 240` activates and honors duration" datum it relied on (2026-07-01) was a *single* write
onto a register that had been idle at 0 for days — not a second write landing 184 ms into an
already-sounding tone.

The tone starts on the `0` and is cut off by the `240`.

### The underlying constraint

Register `13:7` is simultaneously the **activation trigger** and the **duration**:

- a `0` write activates reliably, but `0` means "no auto-stop";
- a non-zero write carries a duration, but activation depends on the value actually changing.

One register cannot deliver both a guaranteed activation and a bounded duration. Every prior fix
picked one horn and was surprised by the other — which is why seven attempts oscillated between
"silent" (ADR-0097, ADR-0099 stuck-register) and "cut short" (this incident). ADR-0100 tried to
get both by writing twice, and the second write silenced the first.

## Decision

**Sound the siren with a single `0`-write and let it run until a human disarms.**

1. The TRIGGERED branch writes `13:9` (volume) and `13:6 = 0` (minutes) as before, then **one**
   `13:7 = 0`. That write is **last in the batch** — nothing may follow it.
2. **No device-side auto-stop.** `13:6` stays pinned to 0 and `13:7` is never written non-zero;
   either would reintroduce a timeout.
3. **No bell cutoff.** `_BURGLAR_SIREN_MAX_TOTAL_SECONDS` (900 s, ADR-0098) is deleted. It worked
   by *declining to re-assert* and letting the device's 240 s timeout expire; with no auto-stop
   remaining, declining to re-assert silences nothing. Silencing would now require actively
   writing a mode indicator, and the requirement is that the alarm sound until disarmed.
4. **Silencing is mode-indicator selection**, which every disarm/arm already performs
   (hardware-verified 2026-07-10). No new mechanism.
5. `resync_ring_keypad_siren` (120 s) is demoted from load-bearing to **watchdog**. It no longer
   sustains the tone; it repairs a siren silenced by a failed write, an external HA/zwave-js
   override, or a keypad reboot. Its interval is no longer coupled to any tone duration.

Both primitives this rests on — "`0` always activates, even over `0`" and "mode-select
silences" — are individually hardware-verified, and the new sequence is a strict *subset* of the
old one, so there is no new untested composition.

## Consequences

### Accepted risks

- **The siren never stops on its own.** If nobody disarms, it sounds indefinitely. A Latchpoint
  crash, container restart, or network partition while triggered leaves the tone running until
  someone disarms at the keypad or cuts power. This was an explicit product decision.
- **Many municipalities cap audible alarm duration** (commonly 15 minutes). This configuration
  does not comply with such a cap. Reintroducing one means an *active* silence — writing the
  mode indicator for the current state — not simply skipping the re-assert.
- **Not verified on hardware before merge.** The diagnosis rests on the recorder trace plus
  ADR-0100's existing matrix, not a live test-fire of the new sequence. This is the same shortcut
  that let earlier attempts ship broken; it was taken knowingly to get a fix out the same night.
  First real trigger is the verification — confirm `13:7` goes to `0` and **stays** there.

### Guardrails against attempt #9

- `test_sync_triggered_sounds_sustained_burglar_siren` asserts `key7_values == [0]` and
  explicitly that **no non-zero `13:7` write occurs**, citing this incident.
- `test_sync_non_triggered_never_touches_burglar_timeout` (ADR-0100's arm-regression guard) is
  unchanged, and now seeds a literal `240` — the stale register prod devices carry over.
- `test_no_bell_cutoff_however_long_the_alarm_has_been_triggered` pins the deleted cutoff.
- `test_siren_reassert_while_already_triggered_still_sounds` covers the watchdog path at driver
  level for the first time — `force_siren_edge=True` with `tracked["state"] == "triggered"`,
  where `entering_triggered` is False and the plain diff computes nothing.

### Migration

None. Prod devices carry `last_written_indicators["13:7"] = 240` from the previous build; the
next trigger writes `0` over it, which activates regardless of what the register held.

## Implementation

1. `backend/control_panels/zwave_ring_keypad_v2.py` — drop the trailing duration write in the
   TRIGGERED branch; delete `_BURGLAR_SIREN_SECONDS` and `_BURGLAR_SIREN_MAX_TOTAL_SECONDS`;
   rewrite the semantic-model comment and the `_desired_indicator_writes` docstring.
2. `backend/control_panels/tasks.py` — remove the bell-cutoff branch and its now-unused imports;
   rewrite the docstring for the watchdog role.
3. `backend/control_panels/tests/test_ring_keypad_v2.py`,
   `backend/control_panels/tests/test_tasks.py` — as above.

## Follow-ups (not in this change)

- **Siren volume is 50 of 99.** `number.back_door_keypad_alarming_burglar_sound_level` = 50; the
  burglar siren plays at roughly half volume. Raising the device's `beep_volume` is a config
  change.
- **Prod has zero enabled notification providers.** This trigger logged `Alarm triggered but no
  enabled notification providers are configured.` — the alarm fired and notified nobody. The
  path has existed since ADR-0098 and has never been configured.
- **`_run_coro` does not cancel on timeout** (`integrations_zwavejs/manager.py`, AUDIT #23): a
  timed-out indicator write can still land on the device seconds later, out of order.
- **`13:1` (burglar multilevel) is latched at 99** on the device from the PR #64 era — state
  nothing in the codebase manages.

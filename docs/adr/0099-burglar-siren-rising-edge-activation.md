# ADR-0099: Burglar Siren Needs a Rising-Edge Activation (Reset-Then-Set + Teardown Clear)

**Status:** Accepted
**Date:** 2026-07-09
**Author:** Leonardo Merza

## Context

### Incident (2026-07-09, prod)

The alarm went `armed_night → pending → triggered` at 11:03:21 UTC and was disarmed at the keypad
at 11:04:48 (~87 s triggered). The keypad made **no sound at all**. Both prior siren fixes were
live in prod at the time — [ADR-0097](0097-ring-keypad-v2-burglar-siren-timeout.md) (#73) and
[ADR-0098](0098-siren-reassert-and-triggered-notification.md) (#74, image built from `7b65049`,
running 5 days) — so "not deployed" was ruled out.

### Root cause: activation is edge-triggered, and the register was stuck

The code fired correctly (prod log `Ring Keypad v2 burglar siren commanded device_id=3` at
11:03:21.030, and **zero** `indicator write failed` lines ever) — the fault is downstream of the
command. HA recorder is the ground truth:

- `number.back_door_keypad_alarming_burglar_timeout_seconds` had been **`240.0` continuously since
  at least 2026-07-05** and did **not change** during the 7/9 trigger. `sound_level` (50),
  `timeout_minutes` (0) and `multilevel` (99) were likewise already at their written values — so
  **all three writes in the TRIGGERED branch were no-ops**.

The Ring Keypad v2 burglar tone starts on a **rising edge** of the Indicator CC (135) indicator 13
`Timeout: Seconds` (property_key 7): `0 → non-zero`. It is *not* enough for the value to be
non-zero. The entry/exit-delay tones work every time only because their countdown value naturally
returns to 0 between uses, so each new cycle re-creates the edge.

The burglar branch, by contrast, wrote a constant `240` and **nothing ever reset the register to
0** — not the trigger branch, not the disarm/arm branches (which silence the tone only by selecting
a *different* mode indicator). Timeline:

- **2026-07-01** (ADR-0098 incident): first real trigger after the ADR-0097 fix; register was `0`,
  write of `240` produced a genuine `0 → 240` edge → **siren sounded** (recorder shows the flip).
- **Ever since:** register stuck at `240`. Every trigger writes `240 → 240` = **no edge → silence**.
  The 2026-07-07 event (24 min triggered, 8 commands + 7 ADR-0098 re-asserts) was **also silent** —
  every re-assert re-wrote `240 → 240`.

This also invalidates a stated assumption in ADR-0098 §1 ("re-writes … `key 7 = 240` and restarts
the tone"): a same-value re-write does **not** restart the tone. The re-assert can only work if each
re-write is a real edge.

## Decision

Guarantee a `0 → non-zero` rising edge on the burglar `key 7` for every trigger, from two
independent directions (defense in depth) in `backend/control_panels/zwave_ring_keypad_v2.py`:

### 1. Teardown clear (primary edge guarantee)

At the top of `_sync_device_state`, whenever `current_state != TRIGGERED`, write burglar
`key 7 = 0` before selecting the mode indicator. This keeps the register at 0 in every
non-triggered state, so the *next* trigger's non-zero write is a clean edge — with **no dependence
on back-to-back write timing**. One extra idempotent Indicator write per non-triggered sync; the
burglar indicator is not sounding in those states, so writing its timeout to 0 is inaudible.

### 2. Reset-then-set on trigger (backstop)

In the TRIGGERED branch, write `key 7 = 0` then `key 7 = _BURGLAR_SIREN_SECONDS`. This covers the
one case the teardown clear cannot: an app restart *while already triggered* (register left
non-zero). It also makes the ADR-0098 re-assert genuinely restart the tone.

### 3. Correct the ADR-0097 test guard

ADR-0097's regression test asserted burglar `key 7 = 0` must **never** appear on trigger — under
the belief "zeroing = silent." That conflates two things. The real invariant is that the write must
not **end** at 0; a *transient* 0 immediately followed by a non-zero is the activation mechanism,
not the bug. The guard is replaced with: an ordered `0` write **precedes** the non-zero write, and
the **final** key-7 write is non-zero.

## Consequences

### Positive
- The siren sounds on **every** trigger, not just the first after a register reset.
- The ADR-0098 re-assert now actually restarts the tone (each re-write is a real edge).
- Self-healing: even if two back-to-back writes ever coalesce, the teardown clear means the next
  trigger still starts from a genuine 0.

### Negative / Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Back-to-back `0 → 240` writes coalesce and produce no device edge on the reset-then-set path. | Low | Low | Teardown clear makes the common-case edge come from an already-0 register, not write timing; not the sole guarantee. |
| Extra Indicator write on every non-triggered sync. | Certain | Negligible | Best-effort, idempotent, inaudible; swallowed on failure like the other mode writes. |
| Not verified on real hardware in this change (no live test-fire). | — | Low | Verified on the next real trigger via HA recorder (see below); teardown clear reduces reliance on the untested timing path. |

### Neutral
- Prod must be redeployed to a `:main` build containing this change (same caveat as ADR-0097/0098).

## Implementation

1. `backend/control_panels/zwave_ring_keypad_v2.py` — non-triggered teardown clear (`key 7 = 0`) at
   the top of `_sync_device_state`; reset (`key 7 = 0`) before the `_BURGLAR_SIREN_SECONDS` write in
   the TRIGGERED branch.
2. `backend/control_panels/tests/test_ring_keypad_v2.py` — trigger test asserts the `0 → non-zero`
   edge (order + non-zero final); new test asserts a non-triggered sync clears `key 7 = 0`.

## Verification

- `./scripts/docker-test.sh` (control_panels suite) + ruff.
- **Next real trigger** (no deliberate noise): confirm the recorder shows a fresh `0 → 240` flip at
  trigger time (not a flat 240) and the keypad audibly sounds, and that it returns to `0` on disarm.

## Related

- [ADR-0097](0097-ring-keypad-v2-burglar-siren-timeout.md) — established the non-zero-timeout siren; its test guard is corrected here.
- [ADR-0098](0098-siren-reassert-and-triggered-notification.md) — the 120 s re-assert, which only works once each re-write is a real edge.

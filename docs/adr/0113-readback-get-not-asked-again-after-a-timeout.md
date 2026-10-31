# ADR-0113: A Readback Get That Times Out Isn't Asked Again

**Status:** Accepted
**Date:** 2026-10-31
**Author:** Leonardo Merza

**Amends:** the readback rule from PR #111 (issue #107) that rides on ADR-0092's push, ie "one timeout is not a verdict, ask up to 3 times", and ADR-0111's budget, whose readbacks it describes

## Context

Since #111 every CC 99 readback (`_verify_user_code_slot`) asks the lock up to
3 times, 1s and then 2s apart, with the caller's timeout on each `get`, which
is 5s everywhere. A lock still committing a write can answer Available once
or 0xfe, and a battery lock can be slow right after a `set`, so one answer
like that or one timeout was never a verdict. The post-set readback, adoption,
the unconfirmed cleanups, the clear retries, the #167 inactive clear, the #183
withdraw, the #180 synced attempt check and lock sync's live readbacks (#194,
#166) all go through it.

A timeout there can't be taken back. `_run_coro` cancels the future (PR #200),
but that only stops our wait, the driver still runs the transaction. So a lock
that takes longer than 5s to answer times out on every `get` even though it
answers each one, and the second and third `get` queue behind the first in the
driver and hold up the other nodes on the controller too (issue #199). That
follows from how the cancel works, nobody has watched it happen on the Yales
yet. A report that never comes back is `None` and a NACK is a fast
`ZwavejsCommandError`. Both of those come back after the driver is done with
the transaction, so asking again doesn't stack anything.

## Decision

- **A timeout ends the readback.** `_run_coro` raises `ZwavejsCommandTimeout`,
  a `ZwavejsCommandError` subclass, only when its own wait runs out and it
  cancels the future. A `TimeoutError` the command raises itself stays a plain
  `ZwavejsCommandError`. The readback doesn't ask again after a
  `ZwavejsCommandTimeout`. It raises `LockCodeUnverified`, with
  `read_back_empty` when an answer before it was empty.
- **One longer wait instead.** Each `get` waits up to
  `_READBACK_GET_TIMEOUT_SECONDS` (15s) and the whole readback, every `get`
  and delay included, ends by `_READBACK_DEADLINE_SECONDS` (18s), which is
  what the 3 `get`s at 5s and the delays took before. Each `get` gets
  `min(15s, what's left of the 18s)`, and a `BudgetedGateway` still cuts that
  to what's left of its budget. The readback has no `timeout_seconds` of its
  own any more, so the callers' 5s doesn't reach the `get`.
- **Answers that aren't a verdict are still asked again.** Empty once, 0xfe,
  no report and a fast `ZwavejsCommandError` still get up to 3 asks with the
  1s and 2s delays, unless the delay doesn't fit before the 18s deadline, in
  which case the readback stops there with `LockCodeUnverified`.
- **The budget works like before.** A `ZwavejsCommandTimeout` once the
  `BudgetedGateway` ran out raises `TimeBudgetExceeded` (or
  `LockCodeUnverified` with `read_back_empty` after an empty answer), the same
  thing a readback that ran out of budget raised before, so the push still
  doesn't count it.
- **A timeout is still no verdict.** Every caller handles `LockCodeUnverified`
  the way it did, so a timed out readback stays transient, the #193 masked
  trust rules and the `slot_read_back_empty` marker are unchanged, and nothing
  is cleared or settled off a timeout.

## Alternatives Considered

- **At most one more `get` after a timeout** (what #199 first asked for). Keeps
  2 of the 3 asks, but a lock slower than 5s still gets 2 stacked `get`s and
  still never answers in time.
- **Stop only after 2 timeouts in a row.** The smallest step, but the second
  `get` still queues behind the first.
- **Wait for the value-updated event instead of the `get`'s answer.** Gets the
  answer whenever it lands, but we can't tell a report from a cache write that
  isn't one, which is the #107 problem again.
- **Adaptive delays.** More to tune and no fewer stacked `get`s on a lock
  that's slower than the timeout.

## Consequences

- A lock that answers in 5s to 15s now gives a verdict, where before every
  `get` timed out and the push stayed pending.
- A `get` the lock never answers isn't followed by one it might have
  answered, so that readback stays unverified until the next retry, the 300s
  retry or adoption on the next push. That's fewer chances to see an empty
  answer too, so slightly fewer `slot_read_back_empty` markers in that case.
- The worst case per readback is still about 18s, so ADR-0111's 30s push
  budget, `SYNC_LOCK_WAIT_SECONDS` (45s) and the request-path cleanups' timing
  don't change. A slot that never answers takes 15s instead of 18s, so lock
  sync's 30s readback budget fits 2 of those instead of 1 and a bit.
- A readback `get` can now hold the driver for up to 15s for one node. Other
  nodes' commands queue behind that one `get` instead of behind 3.
- Errors of anything that timed out read `ZwavejsCommandTimeout: Z-Wave JS
  command timed out after 5.0s` instead of `ZwavejsCommandError: ...`.
- The 15s and 18s weren't measured on the Yales. The QA on the PR is what
  checks them.

## Related ADRs

- [ADR-0092](0092-zwavejs-lock-push-sync.md): push sync, the push the #111 readback is part of.
- [ADR-0111](0111-door-code-push-off-the-request-path.md): the per-lock budget the readback runs inside.

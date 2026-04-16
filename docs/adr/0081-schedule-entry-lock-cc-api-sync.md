# ADR 0081: Schedule Entry Lock — CC API Sync for Daily Repeating Schedules

## Status
**Proposed**

## Context

ADR 0068 introduced lock config sync, which reads user codes (CC 0x63) and schedule slots (CC 0x4C) from a Z-Wave JS lock into LatchPoint's `DoorCode` model. The schedule reading path relies on `node_get_defined_value_ids()` + `node_get_value()` to pull schedule data from Z-Wave JS's in-memory value cache.

Testing against a real lock (Schlage BE469ZP, node 109 on Z-Wave JS server 3.4.0 / driver 15.22.1) revealed three issues:

### 1. Wrong command class constant

The codebase defines:
```python
CC_SCHEDULE_ENTRY_LOCK = 76  # 0x4C
```

CC 76 (0x4C) is actually **Door Lock Logging**, not Schedule Entry Lock. The correct value is **CC 78 (0x4E)**. This affects both `integrations_zwavejs/manager.py` and `locks/use_cases/lock_config_sync.py`.

The `zwave-js-server-python` library confirms:
```
DOOR_LOCK_LOGGING = 76  (0x4C)
SCHEDULE_ENTRY_LOCK = 78  (0x4E)
```

### 2. Schedule values not exposed in Z-Wave JS value cache

Even after correcting the constant, the lock exposes **zero CC 78 value IDs** in the Z-Wave JS value cache. The `start_listening` state dump for node 109 contains 1,055 values (CC 98 Door Lock, CC 99 User Code, CC 112 Configuration, etc.) but none for CC 78 — despite the lock's endpoint 0 declaring support for CC 78 in its command class list.

This means the existing approach (`_extract_weekday_schedule_windows()` reading from `node_get_value()`) will always fall into the early "no schedule value IDs" exit path, marking all slots as `schedule_unsupported`.

### 3. Schedules are accessible via CC API invocation

The Z-Wave JS UI successfully reads and writes schedules on this lock. Investigation shows it uses `endpoint.invoke_cc_api` — a direct command class API call that sends Z-Wave commands over RF, bypassing the value cache.

The `zwave-js-server-python` library (v0.69.0, installed in the production container) already exposes this:
```python
await node.async_invoke_cc_api(
    CommandClass.SCHEDULE_ENTRY_LOCK,
    "getDailyRepeatingSchedule",
    {"userId": 2, "slotId": 1},
    wait_for_result=True,
)
```

### Lock schedule capabilities (node 109)

`getNumSlots()` returns:
```json
{"numWeekDaySlots": 0, "numYearDaySlots": 1, "numDailyRepeatingSlots": 7}
```

This lock supports **daily repeating schedules** only (not weekday schedules). ADR 0068's code only handles weekday schedules and explicitly marks "daily" as unsupported — even if value IDs were found, the schedule data would be discarded.

### Daily repeating schedule API format

`getDailyRepeatingSchedule({userId: 2, slotId: 1})` returns:
```json
{
  "weekdays": [1, 4],
  "startHour": 7,
  "startMinute": 0,
  "durationHour": 8,
  "durationMinute": 0
}
```

Key observations:
- The parameter is a `ScheduleEntryLockSlotId` **object**: `{userId: number, slotId: number}` — not positional args
- `weekdays` is an array of 1-indexed day numbers (1=Monday through 7=Sunday)
- Duration-based window (not start/end) — already handled by `_parse_schedule_entry()`
- Empty schedules return `{}`
- The lock is FLiRS (sleeping); excessive queries cause it to become unresponsive (Z-Wave error code 202)

### Verified schedule data on the lock

| User Slot | PIN | Daily Repeating Schedule |
|-----------|-----|------------------------|
| 1 | 6-digit | No schedule configured |
| 2 | 4-digit | Mon+Thu, 07:00 for 8h (07:00–15:00) |
| 3 | 5-digit | No schedule configured |
| 251 | 6-digit | No schedule configured |

### Relevant ADRs
- **ADR 0068** — Z-Wave JS Lock Config Sync (Codes & Schedules) — original design
- **ADR 0069** — Lock Config Sync: Operational, Security & UX Concerns
- **ADR 0012** — Z-Wave JS Gateway + Connection Manager

## Decision

### 1. Fix the CC constant

Change `CC_SCHEDULE_ENTRY_LOCK` from `76` to `78` in both `manager.py` and `lock_config_sync.py`.

### 2. Add `invoke_cc_api` to the Z-Wave JS gateway layer

Add a new method following the existing `set_value()` pattern:

- **Manager** (`integrations_zwavejs/manager.py`): `invoke_cc_api()` public method + `_async_invoke_cc_api()` async helper. Delegates to the library's `node.async_invoke_cc_api(CommandClass(cc), method, *args, wait_for_result=True)`.
- **Gateway Protocol** (`alarm/gateways/zwavejs.py`): Add `invoke_cc_api()` to the `ZwavejsGateway` Protocol and `DefaultZwavejsGateway` implementation.

This is a general-purpose method — useful beyond schedule sync (e.g., future features like setting lock configurations, triggering node re-interviews, etc.).

### 3. Add daily repeating schedule extraction via CC API fallback

Add `_extract_daily_repeating_schedule_windows_via_cc_api()` to `lock_config_sync.py`. This function:

1. Calls `getNumSlots()` to discover how many daily repeating slots the lock supports.
2. For each occupied user slot, iterates `getDailyRepeatingSchedule({userId, slotId})` for slotId 1..N.
3. Parses the response using the existing `_parse_schedule_entry()` helper (already handles `startHour`/`durationHour` format).
4. Converts the `weekdays` array to a bitmask using the existing `_weekday_to_mask_index()` helper.
5. Outputs the same `{days_of_week, window_start, window_end}` format that `sync_lock_config` expects.

The fallback is triggered when `_extract_weekday_schedule_windows()` finds no CC 78 value IDs in the cache (its early-exit path). If the gateway supports `invoke_cc_api`, it delegates to the new function. Otherwise it returns "unsupported" as before.

### 4. Minimize RF traffic to sleeping devices

Only query schedule slots for **occupied** user codes (the `slot_indices` set from CC 99 enumeration). With typically 2–5 occupied slots and up to 7 daily repeating schedule slots each, this is 14–35 CC API calls — acceptable for a sync operation that runs on explicit user action. If the lock becomes unresponsive mid-query (Z-Wave error 202), the error is caught per-user and that user's schedule is marked unsupported without aborting the entire sync.

## Consequences

### Positive
- Schedule data from physical locks is now importable into LatchPoint for locks that use daily repeating schedules
- The CC constant bug is fixed, unblocking future value-ID-based schedule reads if Z-Wave JS starts caching CC 78 values
- `invoke_cc_api` is available as a general-purpose gateway method for future use
- Backward-compatible: locks that DO expose CC 78 value IDs still use the existing cache-read path

### Negative
- CC API calls generate RF traffic (unlike cached value reads) — the lock must be awake/responsive
- Daily repeating schedules with different time windows across slots for the same user are marked unsupported (matches the existing weekday schedule constraint)
- The `getNumSlots` + per-user iteration pattern means sync takes longer when schedule slots are present (~5–10s per user on FLiRS devices)

### Risks
- Some lock firmwares may not support `endpoint.invoke_cc_api` for CC 78 — these will fail gracefully with the unsupported fallback
- Z-Wave JS server versions older than schema 7 don't support `endpoint.invoke_cc_api` at all — the `hasattr` guard prevents errors

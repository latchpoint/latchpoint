"""Programs door-code PINs and CC 78 schedules onto physical Z-Wave JS locks (ADR 0092).

The companion to ``lock_config_sync.sync_lock_config`` (pull-sync). Whereas
pull-sync reads the lock and reconciles into the DB, ``push_door_code_to_lock``
takes a saved ``DoorCode`` row, picks the lowest free slot on the target lock,
sends CC 99 ``set`` (user code), reads the slot back with CC 99 ``get`` to confirm
the lock stored it, then an optional CC 78 ``setDailyRepeatingSchedule`` per
weekday, and records the slot assignment + push state.

Create, update and Retry queue the push with :func:`request_push` for the
``push_requested_door_codes`` scheduler task, or make it inline where that task
doesn't run in the process (ADR 0111). It commits as much progress as it makes;
transient failures land the row at ``push_state="pending"`` for the scheduler to retry.
"""

from __future__ import annotations

import logging
import re
import time as _time
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Exists, F, OuterRef, Q, Subquery
from django.utils import timezone as django_timezone
from integrations_zwavejs.manager import (
    ZwavejsClientUnavailable,
    ZwavejsCommandValidationError,
    ZwavejsNotConfigured,
)

from alarm.crypto import InvalidToken, SettingsEncryption
from config.domain_exceptions import ConflictError, GatewayError, ValidationError
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.use_cases.code_lifecycle import belongs_on_lock, expired_q, is_started, started_q
from locks.use_cases.lock_config_sync import (
    CC_SCHEDULE_ENTRY_LOCK,
    CC_USER_CODE,
    LockBusy,
    _coerce_int,
    _is_confirmed_empty_status,
    _normalize_pin,
    _parse_user_code_status,
    _release_sync_lock,
    _resolve_lock_node_id,
    _try_acquire_sync_lock,
    clear_lock_user_code_slot,
    hold_lock_sync,
    sync_lock_deadline,
)
from locks.use_cases.lock_config_sync import (
    InvalidRequest as LockSyncInvalidRequest,
)
from locks.use_cases.lock_config_sync import (
    NotFound as LockSyncNotFound,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from alarm.gateways.zwavejs import ZwavejsGateway

logger = logging.getLogger(__name__)

# Weekday bit -> CC 78 ScheduleEntryLockWeekday (Sunday=0, Monday=1 .. Saturday=6).
# Mirrors the read path's _weekday_to_mask_index inversion. NOTE: Sunday is 0, not 7
# — node-zwave-js's ScheduleEntryLockWeekday enum has no value 7.
_WEEKDAY_BIT_TO_ZWAVE = {
    0: 1,  # Monday
    1: 2,
    2: 3,
    3: 4,
    4: 5,
    5: 6,  # Saturday
    6: 0,  # Sunday
}


class InvalidPin(ValidationError):
    """The DoorCode does not carry a usable plaintext PIN (missing/length/format)."""


class LockSlotsFull(ConflictError):
    """The target lock has no Available user-code slots."""


class LockUnreachable(ConflictError):
    """The lock is currently not reachable; safe to retry later."""


class LockPushFailed(GatewayError):
    """The lock returned a terminal error or push retries are exhausted."""

    gateway_name = "zwavejs"


class LockRejectedCode(LockPushFailed):
    """The lock did not store the PIN (a supervised ``set`` came back Fail, or the slot reads back without it).

    ``clear_slot`` is set when the slot we just wrote might still hold the PIN
    (read back holding it disabled, or read back empty but possibly committed
    late), so the push path clears it rather than leave a PIN on the lock nothing
    tracks. ``holds_pin`` is set only when the readback showed the PIN itself,
    and ``holds_other`` only when it showed a different code.
    ``supervision_failed`` is set when the lock answered the ``set`` with a
    Supervision Fail, so nothing was read back (issue #125).
    """

    def __init__(
        self,
        message: str,
        *,
        clear_slot: bool = False,
        holds_pin: bool = False,
        holds_other: bool = False,
        supervision_failed: bool = False,
    ):
        super().__init__(message)
        self.clear_slot = clear_slot
        self.holds_pin = holds_pin
        self.holds_other = holds_other
        self.supervision_failed = supervision_failed


class LockCodeUnverified(GatewayError):
    """The slot could not be read back after the ``set``; transient, the scheduler retries.

    ``read_back_empty`` is set when one of the answers was Available. That's no
    verdict (a lock still committing the write can answer it), but it's enough
    that a masked readback of the slot later isn't counted as this code's
    (issues #128, #152).
    """

    gateway_name = "zwavejs"

    def __init__(self, message: str, *, read_back_empty: bool = False):
        super().__init__(message)
        self.read_back_empty = read_back_empty


class PushSuperseded(LockUnreachable):
    """The code changed while its push waited for the lock (deleted, turned off, lock dropped); nothing was sent."""


class PushInTransaction(RuntimeError):
    """A push was called inside a DB transaction someone else opened (issue #130). Raised in dev and tests only."""


class TimeBudgetExceeded(GatewayError):
    """A call :class:`BudgetedGateway` refused because its time budget ran out. Nothing was sent (issue #124)."""

    gateway_name = "zwavejs"


# How long one lock's push may take, the queued push and the inline fallback alike (issue #124).
# A slow lock that answers runs out of it and is left pending, uncounted, for the next retry.
PUSH_LOCK_BUDGET_SECONDS = 30.0


class BudgetedGateway:
    """Wraps a Z-Wave JS gateway so the calls made through it end by one deadline (issue #124).

    Each call's ``timeout_seconds`` is cut to what's left of the budget, and a
    call once it's used up raises :class:`TimeBudgetExceeded` without reaching
    the gateway. ``exhausted`` is set once that happens or a call fails after the
    deadline, which is how a push tells a lock that ran out of time (not
    counted toward the cap) from one that failed. Everything else is passed
    through, so callers and tests see the same calls.
    """

    def __init__(self, inner: ZwavejsGateway, *, seconds: float):
        self._inner = inner
        self.seconds = float(seconds)
        self.deadline = _time.monotonic() + self.seconds
        self.exhausted = False

    def remaining(self) -> float:
        return self.deadline - _time.monotonic()

    def __getattr__(self, name: str):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            remaining = self.remaining()
            if remaining <= 0:
                self.exhausted = True
                raise TimeBudgetExceeded(f"Ran out of its {self.seconds:g}s time budget before {name}; will retry.")
            timeout = kwargs.get("timeout_seconds")
            if isinstance(timeout, (int, float)) and remaining < timeout:
                kwargs["timeout_seconds"] = remaining
            try:
                return attr(*args, **kwargs)
            except Exception:
                if self.remaining() <= 0:
                    self.exhausted = True
                raise

        return call


def _out_of_budget(zwavejs: object) -> bool:
    """Whether ``zwavejs`` is a :class:`BudgetedGateway` whose budget ran out, ie a failure not to count."""
    return isinstance(zwavejs, BudgetedGateway) and zwavejs.exhausted


def _in_outer_transaction() -> bool:
    """Whether this connection is inside a transaction a caller opened, ``TestCase``'s own aside.

    ``TestCase`` wraps every test in atomic blocks marked ``_from_testcase``, the
    same ones Django's ``atomic(durable=True)`` check lets through, so a push
    called straight from a test doesn't count. Autocommit turned off by hand
    with ``set_autocommit(False)`` does: that leaves ``in_atomic_block`` false
    and no atomic blocks, so it's caught by checking autocommit itself.
    """
    if connection.get_autocommit():
        return False
    blocks = connection.atomic_blocks
    return not blocks or not all(getattr(block, "_from_testcase", False) for block in blocks)


def _check_no_outer_transaction(*, door_code: DoorCode, lock_entity_id: str) -> None:
    """Refuse a push inside a caller's transaction in dev and tests, and log a warning in prod (issue #130).

    Back to back pushes only stay in separate slots because the slot write
    commits before the ``lock_sync:`` lock is let go. Inside an outer
    transaction it doesn't, so a push from another process reads the slots from
    before it, picks the same one and overwrites it on the lock before the
    unique constraint notices (#106). Checked before anything is sent.
    """
    if not _in_outer_transaction():
        return
    message = (
        f"Door code id={door_code.id} is being pushed to {lock_entity_id} inside an open DB transaction, "
        "so its slot won't be committed before the lock_sync lock is released."
    )
    if settings.DEBUG or getattr(settings, "IS_TESTING", False):
        raise PushInTransaction(message)
    logger.warning(message)


# DoorCode fields a push writes to the lock, re-read once the push holds the lock.
_PUSHED_FIELDS = ["encrypted_pin", "is_active", "days_of_week", "window_start", "window_end"]
# Never sent to the lock, but a code is only pushed between them (issue #145), so re-read too.
_VALIDITY_FIELDS = ["start_at", "end_at"]


@dataclass
class PushResult:
    lock_entity_id: str
    node_id: int
    slot_index: int
    schedule_applied: bool = False
    weekdays_pushed: list[int] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _decrypt_pin_or_raise(door_code: DoorCode) -> str:
    """Return the plaintext PIN. Raises :class:`InvalidPin` if missing/unreadable."""
    if not door_code.encrypted_pin:
        raise InvalidPin("Door code has no stored PIN to push.")
    try:
        plaintext = SettingsEncryption.get().decrypt(door_code.encrypted_pin)
    except (ValueError, InvalidToken) as exc:
        raise InvalidPin("Stored PIN could not be decrypted.") from exc
    text = (plaintext or "").strip()
    if not text.isdigit():
        raise InvalidPin("Stored PIN is not numeric.")
    if len(text) < 4 or len(text) > 8:
        raise InvalidPin("Stored PIN must be 4 to 8 digits.")
    return text


def _enumerate_free_slot(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    timeout_seconds: float,
    value_ids: object,
    claimed_slots: set[int] | frozenset[int] = frozenset(),
) -> int:
    """Return the lowest free user-code slot on the node. Raises :class:`LockSlotsFull`.

    Only a slot whose ``userIdStatus`` is Available (0) is free. Messaging (3)
    and PassageMode (4) slots hold lock config, and 0xfe (status not available),
    a missing value or anything unrecognised isn't a verdict, so none of them
    get a PIN written over them (issue #168).

    ``value_ids`` is the node's defined value IDs, which the push fetches once
    and shares with the admin code hint (issue #124).

    ``claimed_slots`` are slots the DB already has a ``DoorCodeLockAssignment`` for
    on this lock. They are skipped even when the Z-Wave JS value cache still reads
    them as Available, which it does for a while after a CC 99 ``set``.
    """
    if not isinstance(value_ids, list):
        value_ids = []

    cc99 = [vid for vid in value_ids if isinstance(vid, dict) and vid.get("commandClass") == CC_USER_CODE]
    if not cc99:
        raise LockPushFailed("Lock does not expose User Code (CC 99) value IDs.")

    users_number_vid = next(
        (vid for vid in cc99 if isinstance(vid.get("property"), str) and vid.get("property") == "usersNumber"),
        None,
    )
    max_slots: int | None = None
    if users_number_vid is not None:
        try:
            raw = zwavejs.node_get_value(node_id=node_id, value_id=users_number_vid, timeout_seconds=timeout_seconds)
            if isinstance(raw, int) and raw > 0:
                max_slots = int(raw)
        except Exception:
            max_slots = None
    if max_slots is None:
        keys: set[int] = set()
        for vid in cc99:
            if vid.get("property") not in {"userIdStatus", "userCode"}:
                continue
            key = vid.get("propertyKey")
            if isinstance(key, int) and key >= 0:
                keys.add(int(key))
        if keys:
            max_slots = max(keys)

    if not isinstance(max_slots, int) or max_slots <= 0:
        raise LockPushFailed("Unable to determine lock user-code slot count.")

    # The lock's own value IDs, so the read uses its real CC 99 endpoint, like lock config sync.
    status_vid_by_slot: dict[int, dict] = {}
    for vid in cc99:
        key = _coerce_int(vid.get("propertyKey"))
        if vid.get("property") == "userIdStatus" and key is not None:
            status_vid_by_slot[key] = vid

    for slot_index in range(1, int(max_slots) + 1):
        if slot_index in claimed_slots:
            continue
        status_vid = status_vid_by_slot.get(slot_index) or {
            "commandClass": CC_USER_CODE,
            "property": "userIdStatus",
            "propertyKey": slot_index,
        }
        try:
            status_value = zwavejs.node_get_value(node_id=node_id, value_id=status_vid, timeout_seconds=timeout_seconds)
        except TimeBudgetExceeded:
            # Out of time, not out of slots (issue #124).
            raise
        except Exception:
            # Treat unknown status as occupied to avoid clobbering a real code.
            continue
        if _is_confirmed_empty_status(status_value):
            return slot_index

    raise LockSlotsFull("No user-code slot on this lock is Available.")


def _refresh_user_code_slot(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    slot_index: int,
    timeout_seconds: float,
) -> object:
    """Send CC 99 ``get`` for one slot so Z-Wave JS re-reads it from the lock.

    Returns whatever the CC API call returns (the slot's status/code report).
    Gateway errors propagate; callers decide whether a failed refresh matters.
    """
    return zwavejs.invoke_cc_api(
        node_id=node_id,
        command_class=CC_USER_CODE,
        method_name="get",
        args=[slot_index],
        timeout_seconds=timeout_seconds,
    )


# CC 99 value properties Z-Wave JS caches the lock's admin code under. ``masterCode``
# is the name from before Z-Wave JS renamed it, which nodes interviewed back then
# may still carry (issue #125).
_ADMIN_CODE_PROPERTIES = ("adminCode", "masterCode")

# Appended to a push error when the lock didn't keep the PIN and the PIN matches
# the admin code Z-Wave JS has cached. That cache is only as fresh as the last
# interview or refresh, so it's a hint, never a reason to hold a push back.
_ADMIN_CODE_HINT = "This PIN may match the lock's admin code."

# The shortest cut-off hint :func:`strip_admin_code_hint` takes off: its first
# three words. A full-length error that just ends in " This" or " This PIN" keeps
# it, and a shorter piece of the hint says nothing about the admin code.
_ADMIN_CODE_HINT_MIN_CUT = len("This PIN may")

# What ``last_push_error`` holds at most, on the code and on each lock.
_PUSH_ERROR_MAX_LENGTH = 500


def _with_admin_code_hint(message: str) -> str:
    """``message`` with :data:`_ADMIN_CODE_HINT` on the end, the message cut first so the whole hint fits in 500.

    A cut that lands inside the hint would leave a piece of it that
    :func:`strip_admin_code_hint` can't tell from ordinary words (PR #200 review).
    """
    suffix = f" {_ADMIN_CODE_HINT}"
    return f"{message[: _PUSH_ERROR_MAX_LENGTH - len(suffix)]}{suffix}"


def _cut_push_error(message: str) -> str:
    """``message`` cut to 500 characters for ``last_push_error``, never in the middle of the admin code hint.

    A hint the cut would land in goes whole, with the space before it, so a
    code-level error that runs long (the ``lock.x:`` and gave-up prefixes on
    each lock's error) never ends in a piece of it (PR #200 review).
    """
    limit = _PUSH_ERROR_MAX_LENGTH
    if len(message) <= limit:
        return message
    start = message.find(_ADMIN_CODE_HINT, max(0, limit - len(_ADMIN_CODE_HINT) + 1))
    if start != -1 and start < limit:
        return message[:start].rstrip()
    return message[:limit]


def strip_admin_code_hint(message: str | None) -> str:
    """``message`` without :data:`_ADMIN_CODE_HINT`, for viewers who aren't admins (PR #198 review).

    The hint tells whoever reads it that their PIN may be the lock's admin code
    (issue #125). Errors are stored with the hint whole or not at all
    (:func:`_with_admin_code_hint`, :func:`_cut_push_error`), but one stored
    before that may end in a hint cut short at 500 characters, so that goes
    too, once at least :data:`_ADMIN_CODE_HINT_MIN_CUT` characters of it are left.
    """
    text = (message or "").replace(f" {_ADMIN_CODE_HINT}", "").replace(_ADMIN_CODE_HINT, "")
    if len(message or "") >= _PUSH_ERROR_MAX_LENGTH:
        for size in range(len(_ADMIN_CODE_HINT) - 1, _ADMIN_CODE_HINT_MIN_CUT - 1, -1):
            cut = f" {_ADMIN_CODE_HINT[:size]}"
            if text.endswith(cut):
                return text[: -len(cut)]
    return text


def _defined_value_ids_once(*, zwavejs: ZwavejsGateway, node_id: int, timeout_seconds: float) -> Callable[[], object]:
    """A fetch of the node's defined value IDs that asks Z-Wave JS at most once per push (issue #124).

    Fetched on the first call, since an adopted slot skips the free-slot search
    and most pushes never need the admin code hint. A fetch that raises isn't
    kept, so the next call asks again.
    """
    fetched: list[object] = []

    def get() -> object:
        if not fetched:
            fetched.append(zwavejs.node_get_defined_value_ids(node_id=node_id, timeout_seconds=timeout_seconds))
        return fetched[0]

    return get


def _pin_may_match_admin_code(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    pin: str,
    timeout_seconds: float,
    get_value_ids: Callable[[], object],
) -> bool:
    """Whether ``pin`` equals the CC 99 ``adminCode`` (or older ``masterCode``) Z-Wave JS has cached for the lock.

    Yale locks silently drop a user code that matches the admin code while the
    ``set`` still returns normally (issue #107). The cached value can be stale
    (the admin code changed at the keypad since the last interview), so this
    only explains a push the lock already turned down and never stops one
    (issue #125). Any read problem counts as no match. The admin code itself is
    never logged or returned. ``get_value_ids`` is the push's
    :func:`_defined_value_ids_once`, so a push that already searched for a free
    slot doesn't fetch the value IDs again.
    """
    try:
        value_ids = get_value_ids()
        admin_vids = [
            vid
            for vid in (value_ids if isinstance(value_ids, list) else [])
            if isinstance(vid, dict)
            and vid.get("commandClass") == CC_USER_CODE
            and vid.get("property") in _ADMIN_CODE_PROPERTIES
        ]
        for admin_vid in admin_vids:
            raw = zwavejs.node_get_value(node_id=node_id, value_id=admin_vid, timeout_seconds=timeout_seconds)
            known, admin_code = _normalize_pin(raw)
            if known and admin_code == pin:
                return True
    except Exception:
        logger.debug("Could not read the cached admin code for node %d", node_id, exc_info=True)
    return False


# Z-Wave JS SupervisionStatus (zwave_js_server.const.SupervisionStatus): NoSupport=0,
# Working=1, Fail=2, Success=255. Only Fail changes what a push does.
_SUPERVISION_STATUS_FAIL = 2


def _supervision_status(result: object) -> int | None:
    """The Supervision status a CC 99 ``set`` came back with, or ``None`` when there isn't a usable one.

    zwave-js-server-python's ``invoke_cc_api`` returns the server's ``response``,
    which for a supervised ``set`` should be a SupervisionResult dict like
    ``{"status": 255}`` and for an unsupervised one nothing (issue #125). That
    shape isn't confirmed against a real lock, so this also takes the dict
    wrapped in ``response`` or ``result`` and an object with a ``status``
    attribute (the library's own ``SupervisionResult``). The status itself has
    to be an int, so ``{"status": "2"}`` doesn't count, and anything else (a
    bare number, a string, a bool) counts as no result.
    """
    if isinstance(result, dict):
        if "status" in result:
            return _int_status(result.get("status"))
        for key in ("response", "result"):
            inner = result.get(key)
            if isinstance(inner, dict) and "status" in inner:
                return _int_status(inner.get("status"))
        return None
    if result is None or isinstance(result, (str, bytes, int, float)):
        return None
    return _int_status(getattr(result, "status", None))


def _int_status(status: object) -> int | None:
    """``status`` when it's a real int (``SupervisionStatus`` is an IntEnum), else ``None``. No strings or bools."""
    if isinstance(status, int) and not isinstance(status, bool):
        return int(status)
    return None


# Delays between CC 99 ``get`` readback attempts after a ``set``. Battery locks
# can be slow to answer right after a write, so one timeout is not a verdict.
_READBACK_RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0)

# CC 99 userIdStatus "Available": the slot is definitively empty.
_USER_ID_STATUS_AVAILABLE = 0
# CC 99 userIdStatus values for a slot the lock uses for its own config (issue #168).
_USER_ID_STATUS_CONFIG_USES = {3: "messaging", 4: "passage mode"}


def _verify_user_code_slot(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    slot_index: int,
    pin: str,
    timeout_seconds: float,
) -> bool:
    """Read ``slot_index`` back with CC 99 ``get`` and confirm it holds ``pin``.

    Returns ``True`` when the lock reported ``pin`` itself and ``False`` when the
    slot reads back occupied with a masked/unreadable code, which is accepted
    (with a warning) since that's all such a lock lets us confirm.

    Raises :class:`LockRejectedCode` (terminal) when the lock answers and the slot
    holds a different code or holds the code disabled, or answers empty twice
    (one empty answer is asked again, since a lock still committing the write can
    report Available right after the set). A Messaging (3) or PassageMode (4)
    slot is lock config, so it's rejected as holding something else
    (``holds_other``), which every caller leaves alone; 0xfe is still no answer.
    Raises :class:`LockCodeUnverified`
    (transient) when no attempt gets a usable answer, including a single empty
    answer followed only by silence. Terminal config errors propagate unchanged.
    """
    attempts = len(_READBACK_RETRY_DELAYS_SECONDS) + 1
    last_reason = "no response"
    empty_answers = 0
    for attempt in range(attempts):
        if attempt:
            _time.sleep(_READBACK_RETRY_DELAYS_SECONDS[attempt - 1])
        try:
            response = _refresh_user_code_slot(
                zwavejs=zwavejs,
                node_id=node_id,
                slot_index=slot_index,
                timeout_seconds=timeout_seconds,
            )
        except (ZwavejsNotConfigured, ZwavejsClientUnavailable):
            raise
        except TimeBudgetExceeded as exc:
            # Out of time is no answer either, and asking again would only sleep
            # (issue #124). An empty answer before it still has to reach the
            # caller, or a masked readback of the slot later counts as ours
            # (issues #128, #152, PR #201 review).
            if empty_answers:
                raise LockCodeUnverified(
                    f"Could not read back slot {slot_index} before running out of time (slot read back empty once).",
                    read_back_empty=True,
                ) from exc
            raise
        except GatewayError as exc:
            last_reason = f"{exc.__class__.__name__}: {exc}"
            continue

        if isinstance(response, dict) and "response" in response:
            response = response["response"]
        if not isinstance(response, dict):
            last_reason = "lock returned no user code report"
            continue

        status = response.get("userIdStatus")
        if _coerce_int(status) == _USER_ID_STATUS_AVAILABLE:
            empty_answers += 1
            if empty_answers >= 2:
                raise LockRejectedCode(
                    f"Lock did not store the code: slot {slot_index} reads back empty.",
                    clear_slot=True,
                )
            last_reason = "slot read back empty once"
            continue
        config_use = _USER_ID_STATUS_CONFIG_USES.get(_coerce_int(status))
        if config_use is not None:
            # Lock config, not a user code and not empty (issue #168). Never ours to clear.
            raise LockRejectedCode(
                f"Lock reports slot {slot_index} as a {config_use} slot, not a user code.", holds_other=True
            )
        occupied, is_active = _parse_user_code_status(status)
        if not occupied:
            # e.g. 254 "status not available" — not a verdict, ask again.
            last_reason = f"unknown userIdStatus {status!r}"
            continue
        known, stored = _normalize_pin(response.get("userCode"))
        if is_active is False:
            # We always send userIdStatus=1 (enabled); a disabled code won't open the door.
            # Only our own PIN gets cleared: a disabled slot with any other or an
            # unreadable code may be someone else's (our set may have been dropped).
            if known and stored == pin:
                raise LockRejectedCode(
                    f"Lock stored the code in slot {slot_index} but reports it disabled.",
                    clear_slot=True,
                    holds_pin=True,
                )
            if known:
                raise LockRejectedCode(
                    f"Lock did not store the code: slot {slot_index} holds a different code.", holds_other=True
                )
            raise LockRejectedCode(f"Lock reports slot {slot_index} disabled and its code can't be read back.")

        if not known:
            logger.warning(
                "Slot %d on node %d reads back occupied but userCode is %s; accepting without comparing",
                slot_index,
                node_id,
                "masked or unreadable" if "userCode" in response else "missing from the report",
            )
            return False
        if stored != pin:
            raise LockRejectedCode(
                f"Lock did not store the code: slot {slot_index} holds a different code.", holds_other=True
            )
        return True

    raise LockCodeUnverified(
        f"Could not read back slot {slot_index} after {attempts} attempts ({last_reason}).",
        read_back_empty=empty_answers > 0,
    )


# DoorCodeEvent metadata ``action`` for a push that sent the PIN to a slot but
# didn't get it confirmed. The slot is what a later retry may adopt.
_UNCONFIRMED_PUSH_ACTION = "push_unconfirmed"

# DoorCodeEvent metadata ``action`` (on a ``code_removed`` event) recorded once a
# cleanup has checked or cleared a ``push_unconfirmed`` slot, so the attempts for
# that lock and slot before it no longer count (issue #161). A ``clear_resolved``
# for the same lock and slot settles them too when the slot was emptied
# (``_SLOT_EMPTIED_OUTCOMES``), see ``_unsettled_unconfirmed_attempts``.
_UNCONFIRMED_RESOLVED_ACTION = "unconfirmed_resolved"

# ``clear_resolved`` outcomes after which the slot holds nothing of the code's,
# whatever PIN an earlier attempt sent there: it was cleared, or the lock is gone.
_SLOT_EMPTIED_OUTCOMES = frozenset({"cleared", "lock_missing"})


# Metadata key for the PIN a recorded slot is expected to hold, encrypted at rest
# like ``DoorCode.encrypted_pin``. The code's PIN may have changed since, so a later
# readback has to compare against this one. Never logged or returned decrypted.
_EXPECTED_PIN_KEY = "encrypted_pin"

# Metadata flag on a ``push_unconfirmed`` attempt the push's own readback accepted (PR #190 review).
_SLOT_VERIFIED_KEY = "slot_verified"

# Metadata flag on a ``push_unconfirmed`` attempt whose ``set`` went into a slot
# the lock reported Available, with no readback of that slot by this code coming
# back empty since its last confirmed push to the lock (issues #128, #152).
_SLOT_AVAILABLE_KEY = "slot_available"

# Metadata flag on an ``unconfirmed_resolved`` or ``clear_resolved`` marker whose
# slot read back empty. An empty slot holds nothing of the code's whatever PIN
# was sent there, so it settles every attempt before it, and no later attempt on
# that slot gets ``slot_available`` until the code's next confirmed push there.
# Any code's marker for the lock and slot also drops the masked-slot trust of
# attempts and clear failures recorded before it (:func:`_masked_trust_dropped`).
_SLOT_EMPTY_KEY = "slot_empty"

# DoorCodeEvent metadata ``action`` (on a ``code_removed`` event, with
# ``slot_empty``) for a readback that answered empty once and then got no
# answer (PR #193 review). That's no verdict, so it settles nothing and a
# readable PIN in the slot still gets cleared, but it drops the masked-slot
# trust like a ``slot_empty`` settle marker does.
_SLOT_SEEN_EMPTY_ACTION = "slot_read_back_empty"


def _encrypt_expected_pin(pin: str | None) -> dict[str, str]:
    return {_EXPECTED_PIN_KEY: SettingsEncryption.get().encrypt(pin)} if pin else {}


def _decrypt_expected_pin(metadata: dict) -> str | None:
    """The PIN stored with :func:`_encrypt_expected_pin`, or ``None`` for older events or an unreadable value."""
    value = metadata.get(_EXPECTED_PIN_KEY) if isinstance(metadata, dict) else None
    if not value:
        return None
    try:
        plaintext = (SettingsEncryption.get().decrypt(str(value)) or "").strip()
    except (ValueError, InvalidToken, TypeError):
        return None
    return plaintext if plaintext.isdigit() else None


def _record_unconfirmed_slot_attempt(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    slot_index: int,
    reason: str,
    pin: str,
    slot_verified: bool = False,
    slot_available: bool = False,
) -> DoorCodeEvent:
    """Remember that ``slot_index`` on this lock may hold ``pin`` for this code (no schema change).

    ``slot_verified`` marks an attempt whose slot the push's own readback already
    accepted, recorded right before its final write (PR #190 review). On a lock
    that masks PINs a later readback of that slot can't show the PIN, so
    adoption and the cleanups count a masked occupied slot as this code's for
    those attempts (:func:`_read_back_attempt_slot`).

    ``slot_available`` marks an attempt whose ``set`` went into a slot the lock
    reported Available, which no readback confirmed (issues #128, #152). The
    cleanups count a masked occupied slot as this code's for those too, and a
    retry sends the ``set`` into that slot again. It's dropped when a readback
    of the slot by this code came back empty since its last confirmed push to
    the lock (:func:`_slot_read_back_empty_since_last_push`), since then the
    slot isn't one this code's PIN can be counted on to stay in.
    """
    if slot_available and _slot_read_back_empty_since_last_push(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index
    ):
        slot_available = False
    return DoorCodeEvent.objects.create(
        door_code=door_code,
        user=door_code.user,
        lock_entity_id=lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata={
            "action": _UNCONFIRMED_PUSH_ACTION,
            "slot_index": int(slot_index),
            "reason": sanitize_push_error_for_storage(reason)[:200],
            **_encrypt_expected_pin(pin),
            **({_SLOT_VERIFIED_KEY: True} if slot_verified else {}),
            **({_SLOT_AVAILABLE_KEY: True} if slot_available else {}),
        },
    )


def _verified_attempt_slots(*, door_code: DoorCode, lock_entity_id: str) -> set[int]:
    """Unsettled attempt slots on this lock whose newest attempt was recorded with ``slot_verified``."""
    return _tagged_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id, key=_SLOT_VERIFIED_KEY)


def _available_attempt_slots(*, door_code: DoorCode, lock_entity_id: str) -> set[int]:
    """Unsettled attempt slots on this lock whose newest attempt was recorded with ``slot_available``."""
    return _tagged_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id, key=_SLOT_AVAILABLE_KEY)


def _tagged_attempt_slots(*, door_code: DoorCode, lock_entity_id: str, key: str) -> set[int]:
    """Unsettled attempt slots whose newest attempt has ``key``, minus those whose trust was dropped since."""
    return {
        slot_index
        for slot_index, (event_id, metadata) in _unsettled_unconfirmed_attempts(
            door_code=door_code, lock_entity_id=lock_entity_id
        ).items()
        if metadata.get(key)
        and not _masked_trust_dropped(lock_entity_id=lock_entity_id, slot_index=slot_index, since_id=event_id)
    }


def _slot_empty_markers(
    *, lock_entity_id: str, slot_index: int, door_code: DoorCode | None = None, after_id: int | None = None
) -> list[int]:
    """Ids of the ``slot_empty`` markers for this lock and slot, every code's unless ``door_code`` is given."""
    markers = _slot_empty_marker_events().filter(lock_entity_id=lock_entity_id, metadata__slot_index=int(slot_index))
    if door_code is not None:
        markers = markers.filter(door_code=door_code)
    if after_id is not None:
        markers = markers.filter(id__gt=after_id)
    return list(markers.values_list("id", flat=True))


def _slot_empty_marker_events():
    """Every ``slot_empty`` marker: settle markers whose slot read back empty, and ``slot_read_back_empty``."""
    return DoorCodeEvent.objects.filter(
        metadata__action__in=[_UNCONFIRMED_RESOLVED_ACTION, _CLEAR_RESOLVED_ACTION, _SLOT_SEEN_EMPTY_ACTION],
        metadata__slot_empty=True,
    )


def _masked_trust_dropped(*, lock_entity_id: str, slot_index: int, since_id: int | None) -> bool:
    """Whether any code's readback of this slot came back empty after event ``since_id`` (PR #193 review).

    Checked when a ``slot_verified`` or ``slot_available`` attempt or clear
    failure is honoured. Latchpoint has seen the slot empty since that event,
    whichever code's readback it was, so a masked code there now may be a
    keypad code and isn't counted as ours.
    """
    if since_id is None:
        return False
    return bool(_slot_empty_markers(lock_entity_id=lock_entity_id, slot_index=slot_index, after_id=since_id))


def _record_slot_read_back_empty(*, door_code: DoorCode, lock_entity_id: str, slot_index: int) -> None:
    """Record a readback of the slot that answered empty once before it got no answer (PR #193 review)."""
    DoorCodeEvent.objects.create(
        door_code=door_code,
        user=door_code.user,
        lock_entity_id=lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_REMOVED,
        metadata={"action": _SLOT_SEEN_EMPTY_ACTION, "slot_index": int(slot_index), _SLOT_EMPTY_KEY: True},
    )


def _slot_read_back_empty_since_last_push(*, door_code: DoorCode, lock_entity_id: str, slot_index: int) -> bool:
    """Whether a readback of this slot by ``door_code`` came back empty since its last successful push to the lock.

    Those readbacks leave a ``slot_empty`` marker (adoption, the unconfirmed
    cleanups, the clear retries, the post-set readback), including one that
    answered empty once and then got no answer. Once there is one, the slot lost
    this code's PIN or never kept it, and a later unconfirmed ``set`` there
    doesn't count a masked readback as ours (PR #192 review, issue #128).
    Another code's markers from before this attempt don't count, since this
    code's own ``set`` went into the slot after them; the ones after it are
    checked when the attempt is honoured (:func:`_masked_trust_dropped`).
    """
    last_pushed_id = (
        DoorCodeEvent.objects.filter(
            door_code=door_code, lock_entity_id=lock_entity_id, event_type=DoorCodeEvent.EventType.CODE_SYNCED
        )
        .order_by("-id")
        .values_list("id", flat=True)
        .first()
    )
    return bool(
        _slot_empty_markers(
            lock_entity_id=lock_entity_id, slot_index=slot_index, door_code=door_code, after_id=last_pushed_id
        )
    )


# What :func:`_read_back_attempt_slot` found in a slot.
_HOLDS_OURS = "ours"
_HOLDS_OTHER = "other"
_READ_BACK_EMPTY = "empty"


def _read_back_attempt_slot(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    slot_index: int,
    pin: str,
    timeout_seconds: float,
    masked_counts: bool,
    disabled_masked_counts: bool = False,
) -> str:
    """Read an unconfirmed attempt slot back. :data:`_HOLDS_OURS` when it holds ``pin``, enabled or disabled.

    With ``masked_counts`` a slot that reads back occupied and enabled with a
    code the lock won't show is ours too, the rule :func:`_tracked_slot_may_hold_pin`
    uses for a tracked slot. That's for a ``slot_verified`` attempt, since this
    push's own readback already accepted it (PR #190 review), and a
    ``slot_available`` one, since the slot was Available when the push picked it
    (issues #128, #152). A disabled slot with a masked code only counts with
    ``disabled_masked_counts``, which is for ``slot_verified`` only: we always
    send the code enabled, so for an attempt nothing confirmed that may be
    someone else's code (PR #193 review).
    :data:`_READ_BACK_EMPTY` when it answers empty twice, and :data:`_HOLDS_OTHER`
    for anything else that isn't ours: a readable different code, a messaging or
    passage mode slot, or a masked one without the flag for it.
    :class:`LockCodeUnverified` and gateway errors propagate.
    """
    try:
        confirmed = _verify_user_code_slot(
            zwavejs=zwavejs, node_id=node_id, slot_index=slot_index, pin=pin, timeout_seconds=timeout_seconds
        )
    except LockRejectedCode as exc:
        if exc.holds_pin:
            return _HOLDS_OURS
        if exc.clear_slot:
            # The only rejection that asks for a clear without holding the PIN.
            return _READ_BACK_EMPTY
        # Left: disabled with a code the lock won't show.
        if exc.holds_other or not disabled_masked_counts:
            return _HOLDS_OTHER
        return _HOLDS_OURS
    return _HOLDS_OURS if confirmed or masked_counts else _HOLDS_OTHER


def _claimed_slots(*, lock_entity_id: str, door_code: DoorCode) -> set[int]:
    """Slots other door codes' assignments hold on this lock (skipped by selection, adoption and cleanup)."""
    return set(
        DoorCodeLockAssignment.objects.filter(lock_entity_id=lock_entity_id, slot_index__isnull=False)
        .exclude(door_code=door_code)
        .values_list("slot_index", flat=True)
    )


def _unconfirmed_attempt_slots(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    claimed_slots: set[int] | frozenset[int] = frozenset(),
) -> list[int]:
    """Slots recorded by :func:`_record_unconfirmed_slot_attempt` for this code on this lock.

    Only attempts since the code's last successful push to this lock count, and
    not ones a cleanup has settled since, newest first, without duplicates or
    ``claimed_slots``.
    """
    return list(_unconfirmed_attempts(door_code=door_code, lock_entity_id=lock_entity_id, claimed_slots=claimed_slots))


def _unconfirmed_attempt_window(*, door_code: DoorCode, lock_entity_id: str):
    """The ``push_unconfirmed`` events for this code on this lock since its last successful push there."""
    events = DoorCodeEvent.objects.filter(door_code=door_code, lock_entity_id=lock_entity_id)
    last_pushed_id = (
        events.filter(event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        .order_by("-id")
        .values_list("id", flat=True)
        .first()
    )
    attempts = events.filter(event_type=DoorCodeEvent.EventType.CODE_FAILED, metadata__action=_UNCONFIRMED_PUSH_ACTION)
    if last_pushed_id is not None:
        attempts = attempts.filter(id__gt=last_pushed_id)
    return attempts


def _unsettled_unconfirmed_attempts(*, door_code: DoorCode, lock_entity_id: str) -> dict[int, tuple[int, dict]]:
    """The newest in-window ``push_unconfirmed`` event per slot that no cleanup has settled since.

    Maps each slot to that event's ``(id, metadata)``, newest first. An
    ``unconfirmed_resolved`` marker for the same lock and slot settles every
    attempt recorded before it (issue #161), and so does a ``clear_resolved``
    whose slot was actually cleared, read back empty or whose lock is gone. Any other
    ``clear_resolved`` (the slot didn't hold the failure's expected PIN, or
    another code tracks it) only says something about the PIN that failure
    expected, so it only settles attempts recorded before that failure. An
    attempt recorded after it was never checked and may hold a newer PIN (PR
    #167 review). A later attempt on a settled slot counts again.
    """
    settled_up_to: dict[int, int] = {}
    open_failure_since: dict[int, int] = {}
    markers = (
        DoorCodeEvent.objects.filter(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            metadata__action__in=[_UNCONFIRMED_RESOLVED_ACTION, _CLEAR_FAILED_ACTION, _CLEAR_RESOLVED_ACTION],
        )
        .order_by("id")
        .values_list("id", "metadata")
    )
    for event_id, metadata in markers:
        slot_index = _coerce_int(metadata.get("slot_index")) if isinstance(metadata, dict) else None
        if not slot_index:
            continue
        action = metadata.get("action")
        if action == _CLEAR_FAILED_ACTION:
            open_failure_since.setdefault(slot_index, event_id)
            continue
        settles = event_id
        if action == _CLEAR_RESOLVED_ACTION:
            failed_at = open_failure_since.pop(slot_index, None)
            if metadata.get("outcome") not in _SLOT_EMPTIED_OUTCOMES and not metadata.get(_SLOT_EMPTY_KEY):
                if failed_at is None:
                    continue
                settles = failed_at
        settled_up_to[slot_index] = max(settled_up_to.get(slot_index, 0), settles)

    newest: dict[int, tuple[int, dict]] = {}
    attempts = _unconfirmed_attempt_window(door_code=door_code, lock_entity_id=lock_entity_id)
    for event_id, metadata in attempts.order_by("-id").values_list("id", "metadata"):
        if not isinstance(metadata, dict):
            continue
        slot_index = _coerce_int(metadata.get("slot_index"))
        if slot_index is None or slot_index <= 0 or slot_index in newest:
            continue
        newest[slot_index] = (event_id, metadata)
    return {
        slot_index: attempt for slot_index, attempt in newest.items() if settled_up_to.get(slot_index, 0) < attempt[0]
    }


def _unconfirmed_attempts(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    claimed_slots: set[int] | frozenset[int] = frozenset(),
) -> dict[int, str | None]:
    """Like :func:`_unconfirmed_attempt_slots`, mapping each slot to the PIN its newest attempt sent.

    The PIN is ``None`` for attempts recorded before it was stored.
    """
    return {
        slot_index: _decrypt_expected_pin(metadata)
        for slot_index, (_event_id, metadata) in _unsettled_unconfirmed_attempts(
            door_code=door_code, lock_entity_id=lock_entity_id
        ).items()
        if slot_index not in claimed_slots
    }


def _find_adoptable_attempted_slot(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    door_code: DoorCode,
    lock_entity_id: str,
    pin: str,
    timeout_seconds: float,
    claimed_slots: set[int] | frozenset[int] = frozenset(),
) -> tuple[int, bool] | None:
    """Return ``(slot, resend)`` for a slot an earlier unconfirmed push of this code wrote on this lock, if it's ours.

    Covers a code that landed while every readback timed out: the slot wasn't
    claimed, so a retry would otherwise write the PIN to a new slot, the lock
    would drop it as a duplicate, and the first slot would keep working with
    nothing tracking it. Only slots recorded by
    :func:`_record_unconfirmed_slot_attempt` for this same code and lock since
    its last successful push there are considered, never an arbitrary slot that
    happens to hold the same PIN (e.g. one entered on the keypad). ``claimed_slots``
    (the DB-held set ``_enumerate_free_slot`` skips) are never adopted, and the
    readback must report the PIN itself; a masked readback doesn't count, except
    for a ``slot_verified`` attempt that sent this same PIN, whose slot the push
    already accepted before its final write rolled back (PR #190 review). Its
    slot is adopted when it reads back occupied and enabled with a masked code.
    ``resend`` is ``False`` for all of these.

    The newest ``slot_available`` attempt that sent this same PIN and reads back
    occupied and enabled with a masked code is returned with ``resend=True``
    (issue #128): nothing has seen the PIN there, but the slot was Available
    when that push picked it, so the caller sends the ``set`` into it again
    instead of putting the PIN in a second slot a lock that drops duplicates
    would reject. The same PIN into the same slot changes nothing if it's
    already there. Claims are checked again right before it's returned, since
    the slot may have been recorded for another code during the readback.

    A slot that reads back empty is settled as ``not_holding_pin`` with
    ``slot_empty``, so the attempt stops counting and no later attempt on it
    counts a masked readback as ours (:func:`_slot_read_back_empty_since_last_push`).
    A slot holding anything else is left for the cleanups, since an attempt that
    sent an older PIN may still be what's in it. :class:`LockCodeUnverified`
    propagates, after leaving a ``slot_read_back_empty`` marker when one of its
    answers was empty.
    """
    attempts = _unconfirmed_attempts(
        door_code=door_code,
        lock_entity_id=lock_entity_id,
        claimed_slots=claimed_slots,
    )
    verified = _verified_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id)
    available = _available_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id)
    for slot_index, attempted_pin in attempts.items():
        try:
            confirmed = _verify_user_code_slot(
                zwavejs=zwavejs,
                node_id=node_id,
                slot_index=slot_index,
                pin=pin,
                timeout_seconds=timeout_seconds,
            )
        except LockCodeUnverified as exc:
            if exc.read_back_empty:
                # Empty once, then no answer: no verdict, but the slot doesn't
                # get counted as ours on a masked readback again (PR #193 review).
                _record_slot_read_back_empty(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index)
                if (slot_index in verified or slot_index in available) and _unresolved_clear_failure(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index
                ) is None:
                    # Superseded by an untagged attempt for the same PIN, so the
                    # drop holds once retention prunes the marker. Not while a
                    # clear failure is open there, since that failure's
                    # clear_resolved only settles the attempts before it; the
                    # retention rule for the marker covers that case.
                    _record_unconfirmed_slot_attempt(
                        door_code=door_code,
                        lock_entity_id=lock_entity_id,
                        slot_index=slot_index,
                        reason=f"Slot {slot_index} read back empty once, then didn't answer",
                        pin=attempted_pin or pin,
                    )
            raise
        except LockRejectedCode as exc:
            if exc.clear_slot and not exc.holds_pin:
                _settle_unconfirmed_slot(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    outcome="not_holding_pin",
                    slot_empty=True,
                )
            continue
        if confirmed or (slot_index in verified and attempted_pin == pin):
            return slot_index, False
        if slot_index in available and attempted_pin == pin:
            if slot_index in _claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code):
                continue
            return slot_index, True
    return None


def decrypt_pin_or_none(door_code: DoorCode) -> str | None:
    """Return the stored plaintext PIN, or ``None`` when it's missing or unreadable."""
    try:
        return _decrypt_pin_or_raise(door_code)
    except InvalidPin:
        return None


def unconfirmed_attempt_lock_entity_ids(*, door_code: DoorCode) -> list[str]:
    """Locks where ``door_code`` has an unconfirmed slot left to check, assigned now or not (issue #134), sorted.

    Only attempts still in their window and not settled by a cleanup count, so a
    lock whose slot was already checked or cleared (ie when it was dropped) stops
    being tied to the code (issue #161).
    """
    candidates = set(
        DoorCodeEvent.objects.filter(
            door_code=door_code,
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata__action=_UNCONFIRMED_PUSH_ACTION,
        )
        .exclude(lock_entity_id="")
        .values_list("lock_entity_id", flat=True)
    )
    return sorted(
        lock_entity_id
        for lock_entity_id in candidates
        if _unsettled_unconfirmed_attempts(door_code=door_code, lock_entity_id=lock_entity_id)
    )


def affected_lock_entity_ids(*, door_code: DoorCode) -> set[str]:
    """Every lock an update or delete of ``door_code`` may send a clear or set to (issue #131).

    Its assigned locks, locks with a clear still outstanding, and locks with an
    unconfirmed push attempt on record.
    """
    locks = set(DoorCodeLockAssignment.objects.filter(door_code=door_code).values_list("lock_entity_id", flat=True))
    locks.update(f.lock_entity_id for f in unresolved_clear_failures(door_code=door_code))
    locks.update(unconfirmed_attempt_lock_entity_ids(door_code=door_code))
    return locks


def has_unconfirmed_attempt_slots(*, door_code: DoorCode) -> bool:
    """Whether any of ``door_code``'s locks has a recorded unconfirmed slot that may hold its PIN."""
    for lock_entity_id in DoorCodeLockAssignment.objects.filter(door_code=door_code).values_list(
        "lock_entity_id", flat=True
    ):
        claimed = _claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code)
        if _unconfirmed_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id, claimed_slots=claimed):
            return True
    return False


# DoorCodeEvent metadata ``action`` for a CC 99 clear that failed transiently, so
# the slot may still hold the PIN (issue #139). A later ``code_removed`` event with
# ``_CLEAR_RESOLVED_ACTION`` for the same lock and slot settles it. No schema change.
_CLEAR_FAILED_ACTION = "clear_failed"
_CLEAR_RESOLVED_ACTION = "clear_resolved"


@dataclass(frozen=True)
class ClearFailure:
    """A slot on a lock that a clear didn't reach, so it may still hold the code's PIN.

    ``removing`` is set when the lock was being dropped from the code (its
    assignment is kept until the clear works). ``unconfirmed`` is set for a slot
    only known from a ``push_unconfirmed`` attempt, which is read back before
    it's cleared. ``permanent`` failures (the lock entity is gone or has no Z-Wave
    node) can't be retried and aren't recorded as events. ``expected_pin`` is the
    PIN the slot is expected to hold, which may not be the code's current one; it
    never goes into ``as_metadata`` or ``repr``. ``slot_verified`` is carried over
    from a ``slot_verified`` unconfirmed attempt (PR #190 review), so the retry
    still counts a masked readback as this code's after a later push to that lock
    has closed the attempt's window. Events from before it was stored read as
    ``False``. ``slot_available`` is carried over from a ``slot_available``
    attempt the same way (issues #128, #152).
    """

    lock_entity_id: str
    slot_index: int
    reason: str
    removing: bool = False
    unconfirmed: bool = False
    permanent: bool = False
    slot_verified: bool = False
    slot_available: bool = False
    expected_pin: str | None = field(default=None, repr=False, compare=False)
    event_id: int | None = field(default=None, compare=False)

    def as_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "lock_entity_id": self.lock_entity_id,
            "slot_index": self.slot_index,
            "reason": self.reason,
        }
        if self.permanent:
            metadata["permanent"] = True
        return metadata


def is_permanent_clear_error(exc: Exception) -> bool:
    """A clear error that retrying can't fix: latchpoint can't resolve the lock to a Z-Wave node."""
    return isinstance(exc, (LockSyncNotFound, LockSyncInvalidRequest))


def _clear_error_reason(exc: Exception) -> str:
    return sanitize_push_error_for_storage(f"{exc.__class__.__name__}: {exc}")[:200]


def unresolved_clear_failures(*, door_code: DoorCode) -> list[ClearFailure]:
    """Clear failures recorded for ``door_code`` that no later clear has settled, oldest first."""
    pending: dict[tuple[str, int], ClearFailure] = {}
    events = (
        DoorCodeEvent.objects.filter(
            door_code=door_code, metadata__action__in=[_CLEAR_FAILED_ACTION, _CLEAR_RESOLVED_ACTION]
        )
        .order_by("id")
        .values_list("id", "lock_entity_id", "metadata")
    )
    for event_id, lock_entity_id, metadata in events:
        slot_index = _coerce_int(metadata.get("slot_index")) if isinstance(metadata, dict) else None
        if not slot_index or slot_index <= 0:
            continue
        key = (lock_entity_id, slot_index)
        if metadata.get("action") == _CLEAR_FAILED_ACTION:
            pending[key] = ClearFailure(
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                reason=str(metadata.get("reason") or ""),
                removing=bool(metadata.get("removing")),
                unconfirmed=bool(metadata.get("unconfirmed")),
                slot_verified=bool(metadata.get(_SLOT_VERIFIED_KEY)),
                slot_available=bool(metadata.get(_SLOT_AVAILABLE_KEY)),
                expected_pin=_decrypt_expected_pin(metadata),
                event_id=event_id,
            )
        else:
            pending.pop(key, None)
    return [_without_dropped_trust(failure) for failure in pending.values()]


def _stored_failure(failure: ClearFailure | None) -> ClearFailure | None:
    """``failure`` with the tags its ``clear_failed`` event stores, before :func:`_without_dropped_trust`."""
    if failure is None or failure.event_id is None:
        return failure
    metadata = DoorCodeEvent.objects.filter(id=failure.event_id).values_list("metadata", flat=True).first()
    if not isinstance(metadata, dict):
        return failure
    return replace(
        failure,
        slot_verified=bool(metadata.get(_SLOT_VERIFIED_KEY)),
        slot_available=bool(metadata.get(_SLOT_AVAILABLE_KEY)),
    )


def _strip_dropped_trust(*, door_code: DoorCode, failure: ClearFailure) -> None:
    """Write a new ``clear_failed`` without the tags :func:`_without_dropped_trust` dropped, if the stored one has them.

    So the drop holds once retention prunes the marker that caused it (PR #193 review).
    """
    stored = _stored_failure(failure)
    if stored is None or not (stored.slot_verified or stored.slot_available):
        return
    if (stored.slot_verified, stored.slot_available) == (failure.slot_verified, failure.slot_available):
        return
    _create_clear_failed_event(door_code=door_code, failure=failure)


def _without_dropped_trust(failure: ClearFailure) -> ClearFailure:
    """``failure`` without its masked-slot tags once any code's readback saw its slot empty (PR #193 review)."""
    if not (failure.slot_verified or failure.slot_available) or not _masked_trust_dropped(
        lock_entity_id=failure.lock_entity_id, slot_index=failure.slot_index, since_id=failure.event_id
    ):
        return failure
    return replace(failure, slot_verified=False, slot_available=False)


def _unresolved_clear_failure(*, door_code: DoorCode, lock_entity_id: str, slot_index: int) -> ClearFailure | None:
    return next(
        (
            f
            for f in unresolved_clear_failures(door_code=door_code)
            if (f.lock_entity_id, f.slot_index) == (lock_entity_id, slot_index)
        ),
        None,
    )


def _create_clear_failed_event(*, door_code: DoorCode, failure: ClearFailure) -> None:
    DoorCodeEvent.objects.create(
        door_code=door_code,
        user=door_code.user,
        lock_entity_id=failure.lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata={
            "action": _CLEAR_FAILED_ACTION,
            "slot_index": int(failure.slot_index),
            "reason": failure.reason,
            **({"removing": True} if failure.removing else {}),
            **({"unconfirmed": True} if failure.unconfirmed else {}),
            **({_SLOT_VERIFIED_KEY: True} if failure.slot_verified else {}),
            **({_SLOT_AVAILABLE_KEY: True} if failure.slot_available else {}),
            **_encrypt_expected_pin(failure.expected_pin),
        },
    )


def describe_clear_failure(
    *, door_code: DoorCode, lock_entity_id: str, slot_index: int, exc: Exception
) -> ClearFailure:
    """Log a failed clear and describe it, without recording anything."""
    logger.warning(
        "Could not clear slot %d on %s for door code id=%s; it may still hold the PIN",
        slot_index,
        lock_entity_id,
        door_code.id,
        exc_info=True,
    )
    return ClearFailure(
        lock_entity_id=lock_entity_id,
        slot_index=slot_index,
        reason=_clear_error_reason(exc),
        permanent=is_permanent_clear_error(exc),
    )


def record_clear_failure(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    slot_index: int,
    exc: Exception,
    expected_pin: str | None,
    removing: bool = False,
    unconfirmed: bool = False,
    slot_verified: bool = False,
    slot_available: bool = False,
) -> ClearFailure:
    """Log a failed clear and, unless it's permanent, record it on the lock so it gets retried.

    ``expected_pin`` is the PIN the slot holds (stored encrypted, since the code's
    PIN may change before the retry). One event per slot until it's settled; a
    repeat failure only adds an event when it changes the flags (a tracked slot
    that's now being dropped, say) or brings the first known expected PIN.
    ``slot_verified`` and ``slot_available`` only mean something for an
    ``unconfirmed`` slot, and once recorded for one they're kept until a
    readback sees the slot empty (:func:`_without_dropped_trust`). The flags are
    compared against the stored event, so a failure whose tags were dropped gets
    a new event without them, which keeps the drop once retention prunes the
    marker that caused it (PR #193 review).
    """
    described = describe_clear_failure(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, exc=exc
    )
    if described.permanent:
        return described

    current = _unresolved_clear_failure(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index)
    stored = _stored_failure(current)
    if current is not None:
        removing = removing or current.removing
        unconfirmed = unconfirmed and current.unconfirmed
        expected_pin = current.expected_pin or expected_pin
        slot_verified = slot_verified or current.slot_verified
        slot_available = slot_available or current.slot_available
    slot_verified = unconfirmed and slot_verified
    slot_available = unconfirmed and slot_available
    failure = ClearFailure(
        lock_entity_id=lock_entity_id,
        slot_index=slot_index,
        reason=described.reason,
        removing=removing,
        unconfirmed=unconfirmed,
        slot_verified=slot_verified,
        slot_available=slot_available,
        expected_pin=expected_pin,
    )
    if stored is None or (
        stored.removing,
        stored.unconfirmed,
        stored.slot_verified,
        stored.slot_available,
        bool(stored.expected_pin),
    ) != (
        removing,
        unconfirmed,
        slot_verified,
        slot_available,
        bool(expected_pin),
    ):
        _create_clear_failed_event(door_code=door_code, failure=failure)
    return failure


def cancel_pending_removal(*, door_code: DoorCode, lock_entity_id: str) -> None:
    """Keep a lock the code was still being dropped from: its failed clear no longer removes the assignment.

    The slot still gets cleared and the lock pushed again (the slot may hold an
    older PIN), it just isn't deleted once that works.
    """
    for failure in unresolved_clear_failures(door_code=door_code):
        if failure.lock_entity_id == lock_entity_id and failure.removing:
            _create_clear_failed_event(
                door_code=door_code,
                failure=ClearFailure(
                    lock_entity_id=failure.lock_entity_id,
                    slot_index=failure.slot_index,
                    reason=failure.reason,
                    unconfirmed=failure.unconfirmed,
                    slot_verified=failure.slot_verified,
                    slot_available=failure.slot_available,
                    expected_pin=failure.expected_pin,
                ),
            )


def resolve_clear_failure(
    *, door_code: DoorCode, lock_entity_id: str, slot_index: int, outcome: str, slot_empty: bool = False
) -> ClearFailure | None:
    """Settle a recorded clear failure for this slot (if any) and return it.

    ``slot_empty`` says the slot read back empty, which settles every
    unconfirmed attempt on it so far (:data:`_SLOT_EMPTY_KEY`).
    """
    current = _unresolved_clear_failure(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index)
    if current is not None:
        DoorCodeEvent.objects.create(
            door_code=door_code,
            user=door_code.user,
            lock_entity_id=lock_entity_id,
            event_type=DoorCodeEvent.EventType.CODE_REMOVED,
            metadata={
                "action": _CLEAR_RESOLVED_ACTION,
                "slot_index": int(slot_index),
                "outcome": outcome,
                **({_SLOT_EMPTY_KEY: True} if slot_empty else {}),
            },
        )
    return current


def forget_cleared_slot(
    *, door_code: DoorCode, lock_entity_id: str, slot_index: int, outcome: str, slot_empty: bool = False
) -> bool:
    """Call once ``slot_index`` on the lock no longer holds the PIN (or can't be reached at all).

    Settles any recorded failure for it and stops tracking the slot. An
    assignment whose lock was being dropped is deleted; any other just loses its
    ``slot_index`` and goes back to ``pending`` so the code gets pushed there
    again. Returns ``True`` when the assignment was deleted. ``slot_empty`` goes
    to :func:`resolve_clear_failure`.
    """
    failure = resolve_clear_failure(
        door_code=door_code,
        lock_entity_id=lock_entity_id,
        slot_index=slot_index,
        outcome=outcome,
        slot_empty=slot_empty,
    )
    assignment = DoorCodeLockAssignment.objects.filter(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index
    )
    if failure is not None and failure.removing:
        assignment.delete()
        return True
    # Needs a push there again, so per lock it's pending, attempts kept (issue #126).
    assignment.update(slot_index=None, push_state=DoorCode.PushState.PENDING, schedule_pending=False)
    return False


def clear_failures_message(failures: list[ClearFailure]) -> str:
    return "; ".join(
        f"Couldn't clear slot {f.slot_index} on {f.lock_entity_id}, it may still hold the PIN ({f.reason})"
        for f in failures
    )


def _push_max_attempts() -> int:
    """``door_codes.push_max_attempts``, read through the scheduler's helper so a patch of it applies here too."""
    from locks.tasks import _get_push_max_attempts

    return _get_push_max_attempts()


def _lock_needs_push(assignment: DoorCodeLockAssignment) -> bool:
    """Whether a lock still needs a ``set`` (no slot) or its schedule (``schedule_pending``), whatever its state."""
    return assignment.slot_index is None or assignment.schedule_pending


def _lock_error_part(assignment: DoorCodeLockAssignment, *, max_attempts: int) -> str:
    """``"lock.x: <error>"`` for the code-level error, or ``""`` for a lock with nothing to say."""
    error = assignment.last_push_error or ""
    gave_up = (
        assignment.push_state == DoorCode.PushState.FAILED
        and max_attempts > 0
        and (assignment.push_attempt_count or 0) >= max_attempts
    )
    if gave_up:
        # The cap can fail a lock with no error of its own (a busy lock, PushSuperseded).
        prefix = f"Push gave up after {assignment.push_attempt_count} attempts"
        error = f"{prefix}: {error}" if error else prefix
    if not error:
        return ""
    return f"{assignment.lock_entity_id}: {error}"


def _derive_push_state(*, code: DoorCode, unrecorded_failures: list[ClearFailure]) -> tuple[str, str, bool]:
    """The rollup :func:`refresh_push_state` writes, as ``(push_state, last_push_error, reset_clear_count)``."""
    pending, pushed, failed = DoorCode.PushState.PENDING, DoorCode.PushState.PUSHED, DoorCode.PushState.FAILED
    failures = unresolved_clear_failures(door_code=code)
    recorded = {(f.lock_entity_id, f.slot_index) for f in failures}
    extra = [f for f in unrecorded_failures if (f.lock_entity_id, f.slot_index) not in recorded]
    assignments = list(DoorCodeLockAssignment.objects.filter(door_code=code).order_by("lock_entity_id"))
    max_attempts = _push_max_attempts()
    clear_parts = [clear_failures_message([*failures, *extra])] if failures or extra else []

    # 1. Nothing on any lock and nothing left to clear (issue #142, PR #157).
    if not assignments and not failures:
        return (pending if code.is_active else pushed), "", True

    # The clear-retry cap stays at code level and counts clear retries only (issue #126).
    def clears_capped(outstanding: bool) -> bool:
        return outstanding and max_attempts > 0 and (code.push_attempt_count or 0) >= max_attempts

    lock_parts: list[str] = []
    if not code.is_active or not is_started(code):
        # 2. Off its locks: inactive, or active before its start (issues #138, #145).
        if code.is_active:
            to_clear = _slots_that_may_hold_pin(door_code=code, failures=failures)
        else:
            to_clear = inactive_slots_to_clear(door_code=code, failures=failures)
        outstanding = bool(failures or extra or to_clear)
        state = pending if outstanding or code.is_active else pushed
        capped = clears_capped(outstanding)
    else:
        # 3. Active and started: the locks decide, pending-removal ones aside (issue #126).
        removing = {f.lock_entity_id for f in failures if f.removing}
        considered = [a for a in assignments if a.lock_entity_id not in removing]
        outstanding = bool(failures or extra)
        capped = clears_capped(outstanding)
        if any(a.push_state == failed for a in considered):
            # Needs a human, even while another lock is still being retried.
            state = failed
        elif outstanding or any(a.push_state != pushed or _lock_needs_push(a) for a in considered):
            # A clear failure never lets the code show pushed (issue #139).
            state = pending
        else:
            state = pushed
        lock_parts = [
            part
            for a in considered
            if a.push_state != pushed or _lock_needs_push(a)
            if (part := _lock_error_part(a, max_attempts=max_attempts))
        ]
    if capped:
        state = failed
        clear_parts.append(f"Push gave up after {code.push_attempt_count} attempts")
    error = _cut_push_error(sanitize_push_error_for_storage("; ".join([*clear_parts, *lock_parts])))
    return state, error, not outstanding


def refresh_push_state(
    *,
    door_code: DoorCode,
    unrecorded_failures: list[ClearFailure] | tuple[()] = (),
    only_if_active: bool | None = None,
) -> str | None:
    """Work out the code-level ``push_state`` and ``last_push_error`` from its locks and clears, and save them.

    The one writer of both (issues #126, #123). In order:

    1. No assignments and no unresolved clear failures: an active code is
       ``pending`` (like a new code without locks), an inactive one ``pushed``
       (PR #157).
    2. Inactive, or active before its start: ``pending`` while a clear failure,
       a slot :func:`inactive_slots_to_clear` finds or one
       :func:`slots_to_withdraw` finds is outstanding, else ``pushed`` when
       inactive and ``pending`` (scheduled) when active.
    3. Active and started: ignoring locks being dropped, ``failed`` when any lock
       is ``failed``, else ``pending`` when any lock still needs its ``set`` or
       schedule or a clear failure is outstanding, else ``pushed``.

    In 2 and 3 the code-level clear-retry count at or over
    ``door_codes.push_max_attempts`` with a clear outstanding makes it
    ``failed`` (PRs #144, #167, #183). That count goes back to 0 once nothing is
    left to clear. ``last_push_error`` leads with the slots that may still hold
    the PIN, then has ``"lock.x: <error>"`` for each lock in 3 that isn't
    pushed. ``unrecorded_failures`` are clears still outstanding that left no
    event (a lock still busy, a readback with no answer) and only go in the error.

    Takes the code row first (``select_for_update``), so it's never
    interleaved with another rollup or with a writer of the code and its
    assignments. ``only_if_active`` leaves the row alone unless ``is_active``
    still matches it (PR #167 review). Sets the fields on ``door_code`` too, and
    returns the state, or ``None`` when nothing was looked at (gone, or
    ``only_if_active`` didn't match).
    """
    with transaction.atomic():
        code = DoorCode.objects.select_for_update().filter(id=door_code.id).first()
        if code is None or (only_if_active is not None and code.is_active != only_if_active):
            return None
        state, error, reset_count = _derive_push_state(code=code, unrecorded_failures=list(unrecorded_failures))
        changes: dict[str, object] = {}
        if code.push_state != state:
            changes["push_state"] = state
        if code.last_push_error != error:
            changes["last_push_error"] = error
        if reset_count and code.push_attempt_count:
            changes["push_attempt_count"] = 0
        if changes:
            changes["updated_at"] = django_timezone.now()
            DoorCode.objects.filter(id=code.id).update(**changes)
    door_code.push_state = state
    door_code.last_push_error = error
    door_code.push_attempt_count = changes.get("push_attempt_count", code.push_attempt_count)
    return state


def _lock_code_row(door_code_id: int) -> DoorCode | None:
    """Take the code row inside the caller's transaction, before any of its assignment rows (PR #195 review)."""
    return DoorCode.objects.select_for_update().filter(id=door_code_id).first()


def _locks_being_removed(*, door_code: DoorCode) -> set[str]:
    """Locks the code is being dropped from whose clear hasn't worked yet (issue #151)."""
    return {f.lock_entity_id for f in unresolved_clear_failures(door_code=door_code) if f.removing}


def locks_to_push(
    *,
    door_code: DoorCode,
    assignments: list[DoorCodeLockAssignment] | None = None,
    include_failed: bool = False,
    only_unassigned: bool = True,
) -> list[DoorCodeLockAssignment]:
    """The locks a push of ``door_code`` sends something to, in ``assignments`` order (default by pk).

    With ``only_unassigned`` (the default) only locks that need it: no slot,
    or a slot whose schedule is pending. Never a lock being dropped (issue
    #151), never a slot that still has a clear outstanding (it may hold an
    older PIN, so a schedule-only resend there would give that PIN the new
    window, PR #196 review), and a ``failed`` lock only with ``include_failed``.
    """
    if assignments is None:
        assignments = list(DoorCodeLockAssignment.objects.filter(door_code=door_code).order_by("pk"))
    failures = unresolved_clear_failures(door_code=door_code)
    removing = {f.lock_entity_id for f in failures if f.removing}
    clearing = {(f.lock_entity_id, f.slot_index) for f in failures}
    return [
        a
        for a in assignments
        if a.lock_entity_id not in removing
        and (not only_unassigned or _lock_needs_push(a))
        and (include_failed or a.push_state != DoorCode.PushState.FAILED)
        and not (a.slot_index is not None and (a.lock_entity_id, int(a.slot_index)) in clearing)
    ]


def being_removed_q() -> Exists:
    """:func:`_locks_being_removed` as a filter on ``DoorCodeLockAssignment`` rows (PR #196 review).

    The lock has a ``clear_failed`` with ``removing`` that no later
    ``clear_failed`` or ``clear_resolved`` for the same lock and slot replaced,
    the same newest-event-wins rule :func:`unresolved_clear_failures` uses.
    """
    replaced = DoorCodeEvent.objects.filter(
        door_code=OuterRef("door_code"),
        lock_entity_id=OuterRef("lock_entity_id"),
        metadata__action__in=[_CLEAR_FAILED_ACTION, _CLEAR_RESOLVED_ACTION],
        metadata__slot_index=OuterRef("metadata__slot_index"),
        id__gt=OuterRef("id"),
    )
    return Exists(
        DoorCodeEvent.objects.filter(
            door_code=OuterRef("door_code_id"),
            lock_entity_id=OuterRef("lock_entity_id"),
            metadata__action=_CLEAR_FAILED_ACTION,
            metadata__removing=True,
        ).exclude(Exists(replaced))
    )


def normalize_assignment_push_state() -> int:
    """Repair per-lock push state that drifted from its slot. Run at the start of each scheduler tick.

    The invariants are that ``pushed`` means a slot and no ``schedule_pending``,
    a slot that isn't ``pushed`` has ``schedule_pending``, and ``pending``
    without a slot needs a ``set``. A rollback to code that doesn't write the
    per-lock columns, then a roll forward, breaks them (PR #195 review), so:

    - ``failed`` on an active code whose own state isn't ``failed`` is stale
      (old code pushed or reset it since), unless the code is being dropped
      from that lock, which the rollup ignores. It's re-derived from the code, back
      to ``pending`` with the code's attempt count, then the rules below. On a
      code before its start that's also how a lock the 0010 backfill marked
      ``failed`` goes back to waiting for the start, while the code is
      ``pending`` (scheduled)
    - a slot that isn't ``pushed`` without ``schedule_pending`` is ``pushed``
    - no slot with ``pushed`` or ``schedule_pending`` is ``pending`` without it

    Each code with a drifted lock is repaired in its own transaction, taking
    the code row before its assignments like every other writer of both, then
    refreshed. Returns how many locks it changed.
    """
    assignments = DoorCodeLockAssignment.objects
    pending, pushed, failed = DoorCode.PushState.PENDING, DoorCode.PushState.PUSHED, DoorCode.PushState.FAILED
    rules = [
        (
            # Not a lock being dropped: the rollup ignores it, so its code can be
            # non-failed with the lock failed for real (PR #196 review).
            Q(push_state=failed, door_code__is_active=True) & ~Q(door_code__push_state=failed) & ~being_removed_q(),
            {
                "push_state": pending,
                "push_attempt_count": Subquery(
                    DoorCode.objects.filter(id=OuterRef("door_code_id")).values("push_attempt_count")[:1]
                ),
            },
        ),
        (
            Q(slot_index__isnull=False, schedule_pending=False) & ~Q(push_state=pushed),
            {"push_state": pushed, "push_attempt_count": 0, "last_push_error": ""},
        ),
        (
            Q(slot_index__isnull=True) & (Q(push_state=pushed) | Q(schedule_pending=True)),
            {"push_state": pending, "schedule_pending": False},
        ),
    ]
    drifted = Q()
    for condition, _fields in rules:
        drifted |= condition
    changed = 0
    for code_id in sorted(set(assignments.filter(drifted).values_list("door_code_id", flat=True))):
        with transaction.atomic():
            code = _lock_code_row(code_id)
            if code is None:
                continue
            # In order, each against what the one before left, and the condition
            # again so a row that changed since it was read is left alone.
            for condition, fields in rules:
                changed += assignments.filter(condition, door_code_id=code_id).update(**fields)
            refresh_push_state(door_code=code)
    if changed:
        logger.info("Repaired the push state of %d door code lock(s) that drifted from their slots", changed)
    return changed


def sweep_push_cap(*, now: datetime, max_attempts: int) -> int:
    """Fail every lock still waiting on a push whose own attempt count reached the cap (issue #126).

    Runs every tick, whatever was tried, since a lock can be ``pending`` with
    its count already at or over the cap without being tried: counts aren't
    reset by another lock's success, ``door_codes.push_max_attempts`` can be
    lowered, and the push arm only picks locks under it (PR #195 review). Only
    for codes the scheduler pushes, ie active, started and not expired at the
    tick's ``now``, so it errs toward ``pending``. A lock keeps its own error
    and count and gets a ``max_attempts_exceeded`` event, locks being dropped
    are left alone, and the code is refreshed. One transaction per code, taking
    the code row first like :func:`_delete_door_code_locked` does, so the two
    can't deadlock. Returns how many locks it failed.
    """
    if max_attempts <= 0:
        return 0
    pushable = DoorCode.objects.filter(is_active=True).filter(started_q(now) & ~expired_q(now))
    over_cap = DoorCodeLockAssignment.objects.filter(
        door_code__in=pushable, push_state=DoorCode.PushState.PENDING, push_attempt_count__gte=max_attempts
    ).filter(Q(slot_index__isnull=True) | Q(schedule_pending=True))
    swept = 0
    for code_id in sorted(set(over_cap.values_list("door_code_id", flat=True))):
        with transaction.atomic():
            code = _lock_code_row(code_id)
            if code is None:
                continue
            rows = list(
                over_cap.filter(door_code_id=code_id)
                .exclude(lock_entity_id__in=_locks_being_removed(door_code=code))
                .values_list("id", "lock_entity_id", "push_attempt_count", "last_push_error")
            )
            if not rows:
                continue
            swept += over_cap.filter(id__in=[row[0] for row in rows]).update(push_state=DoorCode.PushState.FAILED)
            for _row_id, lock_entity_id, attempts, error in rows:
                DoorCodeEvent.objects.create(
                    door_code=code,
                    user=code.user,
                    lock_entity_id=lock_entity_id,
                    event_type=DoorCodeEvent.EventType.CODE_FAILED,
                    metadata={
                        "action": "push",
                        "reason": "max_attempts_exceeded",
                        "attempts": attempts,
                        "last_error": sanitize_push_error_for_storage(error)[:200],
                    },
                )
            refresh_push_state(door_code=code)
    return swept


def rearm_failed_locks(*, door_code: DoorCode, max_attempts: int | None = None) -> int:
    """Put the code's ``failed`` locks back to ``pending`` with no attempts or error, then refresh it.

    With ``max_attempts``, ``pending`` locks at or over it go back to 0 too, so
    Retry doesn't leave one the cap is about to fail (PR #195 review). A lock
    whose slot was kept for a terminal schedule failure keeps its slot and
    ``schedule_pending``, so only the schedule goes out again. Code row first.
    Returns how many locks it changed.
    """
    condition = Q(push_state=DoorCode.PushState.FAILED)
    if max_attempts is not None and max_attempts > 0:
        condition |= Q(push_state=DoorCode.PushState.PENDING, push_attempt_count__gte=max_attempts)
    with transaction.atomic():
        if _lock_code_row(door_code.id) is None:
            return 0
        changed = (
            DoorCodeLockAssignment.objects.filter(door_code=door_code)
            .filter(condition)
            .update(push_state=DoorCode.PushState.PENDING, push_attempt_count=0, last_push_error="")
        )
        refresh_push_state(door_code=door_code)
    return changed


def _read_back_failed_slot(
    *,
    zwavejs: ZwavejsGateway,
    lock_entity_id: str,
    slot_index: int,
    pin: str | None,
    timeout_seconds: float,
    masked_counts: bool = False,
    disabled_masked_counts: bool = False,
) -> str:
    """Read the slot back with :func:`_read_back_attempt_slot`; :data:`_HOLDS_OURS` only when it reports ``pin``.

    With ``masked_counts`` (a ``slot_verified`` or ``slot_available`` attempt
    slot) it's ours too when it reads back occupied with a masked code, and with
    ``disabled_masked_counts`` (``slot_verified`` only) when that code is
    disabled. With no ``pin`` to compare against nothing is read and it's
    :data:`_HOLDS_OTHER`.
    """
    if not pin:
        return _HOLDS_OTHER
    return _read_back_attempt_slot(
        zwavejs=zwavejs,
        node_id=_resolve_lock_node_id(lock_entity_id=lock_entity_id),
        slot_index=slot_index,
        pin=pin,
        timeout_seconds=timeout_seconds,
        masked_counts=masked_counts,
        disabled_masked_counts=disabled_masked_counts,
    )


def _held_by_another_code(*, door_code: DoorCode, lock_entity_id: str, slot_index: int) -> bool:
    return (
        DoorCodeLockAssignment.objects.filter(lock_entity_id=lock_entity_id, slot_index=slot_index)
        .exclude(door_code=door_code)
        .exists()
    )


def _retry_failed_slot_clear(
    *,
    door_code: DoorCode,
    failure: ClearFailure,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float,
) -> ClearFailure | None:
    """One clear for :func:`retry_failed_slot_clears`; returns the failure if it's still failing."""
    lock_entity_id, slot_index = failure.lock_entity_id, failure.slot_index
    tracked_here = DoorCodeLockAssignment.objects.filter(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index
    ).exists()
    if _held_by_another_code(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index) or (
        failure.unconfirmed and tracked_here
    ):
        resolve_clear_failure(
            door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="tracked"
        )
        return None
    try:
        if not tracked_here:
            verdict = _read_back_failed_slot(
                zwavejs=zwavejs,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                pin=failure.expected_pin or decrypt_pin_or_none(door_code),
                timeout_seconds=timeout_seconds,
                # Carried on the failure, since a later push to this lock closes the
                # attempt's window. Only an unconfirmed slot's tags count (issues #128, #152).
                masked_counts=failure.unconfirmed and (failure.slot_verified or failure.slot_available),
                disabled_masked_counts=failure.unconfirmed and failure.slot_verified,
            )
            if verdict != _HOLDS_OURS:
                forget_cleared_slot(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    outcome="not_holding_pin",
                    slot_empty=verdict == _READ_BACK_EMPTY,
                )
                return None
            # Checked again after the readback, right before the clear: a slot
            # another code took meanwhile holds its PIN now, not this one's.
            if _held_by_another_code(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index):
                resolve_clear_failure(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="tracked"
                )
                return None
        clear_lock_user_code_slot(
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            zwavejs=zwavejs,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        if is_permanent_clear_error(exc):
            logger.warning("Can't resolve %s to clear slot %d; no longer tracking it", lock_entity_id, slot_index)
            forget_cleared_slot(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
            )
            return None
        logger.warning(
            "Retrying the clear of slot %d on %s for door code id=%s failed again",
            slot_index,
            lock_entity_id,
            door_code.id,
            exc_info=True,
        )
        seen_empty = isinstance(exc, LockCodeUnverified) and exc.read_back_empty
        if seen_empty:
            # Still retried, but the failure's masked-slot tags stop counting (PR #193 review).
            _record_slot_read_back_empty(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index)
            _strip_dropped_trust(
                door_code=door_code,
                failure=replace(failure, reason=_clear_error_reason(exc), slot_verified=False, slot_available=False),
            )
        return ClearFailure(
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            reason=_clear_error_reason(exc),
            removing=failure.removing,
            unconfirmed=failure.unconfirmed,
            slot_verified=failure.slot_verified and not seen_empty,
            slot_available=failure.slot_available and not seen_empty,
        )
    forget_cleared_slot(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="cleared")
    return None


def retry_failed_slot_clears(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 5.0,
    budget_seconds: float | None = None,
) -> list[ClearFailure]:
    """Retry the clears recorded by :func:`record_clear_failure`. Returns the ones still failing.

    ``budget_seconds`` bounds the whole call, lock waits and Z-Wave JS calls
    together (:class:`BudgetedGateway`), for Retry's request (issue #124). A
    clear that doesn't fit keeps its ``clear_failed`` event, so it's still
    outstanding and the scheduler retries it.

    A slot held by another code's assignment now is settled as ``tracked`` and
    never touched, as is an unconfirmed slot this code's assignment now tracks
    (it was adopted or overwritten with the current PIN). A slot this code still
    tracks is cleared as is. Any other slot is read back first and only cleared
    when it holds the PIN it was expected to hold (the code's current PIN for
    failures recorded before that was stored), or for an unconfirmed slot tagged
    ``slot_verified`` or ``slot_available`` when it reads back occupied with a
    masked code (issue #152). Otherwise it's settled as ``not_holding_pin``, with
    ``slot_empty`` when it read back empty. A cleared slot is forgotten (:func:`forget_cleared_slot`),
    so a kept lock gets pushed again and a dropped lock's assignment goes. A lock
    that can't be resolved any more is settled as ``lock_missing``. A failure
    still failing bumps ``push_attempt_count`` so the scheduler's attempt cap
    applies.

    Each lock's clears run while holding its ``lock_sync:`` lock (waiting for it,
    issue #131), and its failures are read again once it's held, since an update
    or delete may have settled them meanwhile. All the locks share one wait
    deadline, so a call waits at most :data:`SYNC_LOCK_WAIT_SECONDS` in total. A
    lock still busy at the deadline is returned as still failing but isn't
    counted toward the attempt cap, since nothing was tried on it.
    """
    still_failing: list[ClearFailure] = []
    attempted_and_failed = False
    deadline = sync_lock_deadline()
    if budget_seconds is not None:
        zwavejs = BudgetedGateway(zwavejs, seconds=budget_seconds)
        deadline = min(deadline, zwavejs.deadline)
    failures = unresolved_clear_failures(door_code=door_code)
    for lock_entity_id in sorted({f.lock_entity_id for f in failures}):
        try:
            with hold_lock_sync([lock_entity_id], deadline=deadline):
                for failure in unresolved_clear_failures(door_code=door_code):
                    if failure.lock_entity_id != lock_entity_id:
                        continue
                    still = _retry_failed_slot_clear(
                        door_code=door_code, failure=failure, zwavejs=zwavejs, timeout_seconds=timeout_seconds
                    )
                    if still is not None:
                        still_failing.append(still)
                        attempted_and_failed = True
        except LockBusy as exc:
            logger.warning(
                "Skipping the clear retries on %s for door code id=%s: %s", lock_entity_id, door_code.id, exc
            )
            still_failing.extend(
                ClearFailure(
                    lock_entity_id=f.lock_entity_id,
                    slot_index=f.slot_index,
                    reason=_clear_error_reason(exc),
                    removing=f.removing,
                    unconfirmed=f.unconfirmed,
                    slot_verified=f.slot_verified,
                    slot_available=f.slot_available,
                )
                for f in failures
                if f.lock_entity_id == lock_entity_id
            )

    if attempted_and_failed:
        door_code.refresh_from_db(fields=["push_attempt_count"])
        door_code.push_attempt_count = (door_code.push_attempt_count or 0) + 1
        door_code.last_push_attempt_at = django_timezone.now()
        door_code.save(update_fields=["push_attempt_count", "last_push_attempt_at", "updated_at"])
    return still_failing


def clear_unconfirmed_slots_holding_pin(
    *,
    door_code: DoorCode,
    pin: str,
    lock_entity_ids: list[str],
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 5.0,
) -> tuple[list[dict[str, object]], list[ClearFailure]]:
    """Clear slots an unconfirmed push of ``door_code`` may have left its PIN in.

    For deleting, deactivating or changing the PIN of a code that is still
    pending: its PIN may have landed in a slot latchpoint never recorded
    (``slot_index`` stays empty until the readback confirms), so the usual
    "clear assigned slots" pass misses it. Candidates are the same recorded
    attempts adoption uses. A slot is cleared only when it reads back holding the
    PIN that attempt sent (``pin``, the code's PIN before this change, for
    attempts recorded before that was stored), enabled or disabled; empty, masked
    or different codes are left alone. A slot that can't be checked or cleared is
    recorded with :func:`record_clear_failure` (``unconfirmed``, with that PIN)
    so it's retried. A lock latchpoint can't resolve to a Z-Wave node any more
    gives a ``permanent`` failure per slot instead (nothing recorded to retry,
    but the caller can still put it in its event, issue #134). Returns the slots
    cleared as ``{"lock_entity_id", "slot_index"}`` dicts and the failures.

    Each lock is checked while holding its ``lock_sync:`` lock (a no-op for a
    caller already holding it), and a slot is skipped if another code's
    assignment holds it by the time it would be cleared (issue #131).
    """
    cleared: list[dict[str, object]] = []
    failed: list[ClearFailure] = []
    deadline = sync_lock_deadline()
    for lock_entity_id in dict.fromkeys(lock_entity_ids):
        with hold_lock_sync([lock_entity_id], deadline=deadline):
            lock_cleared, lock_failed = _clear_unconfirmed_slots_on_lock(
                door_code=door_code,
                pin=pin,
                lock_entity_id=lock_entity_id,
                zwavejs=zwavejs,
                timeout_seconds=timeout_seconds,
            )
        cleared.extend(lock_cleared)
        failed.extend(lock_failed)
    return cleared, failed


def _settle_unconfirmed_slot(
    *, door_code: DoorCode, lock_entity_id: str, slot_index: int, outcome: str, slot_empty: bool = False
) -> None:
    """Record that an unconfirmed slot was checked or cleared, so its attempts stop counting (issue #161).

    Settles a recorded clear failure for the slot if there is one, and adds an
    ``unconfirmed_resolved`` marker unless that failure's ``clear_resolved``
    already settles the attempts (the slot was emptied). The caller checked the
    slot against its newest attempt, so the marker covers every attempt so far.
    ``slot_empty`` says the slot read back empty, which goes on whichever marker
    is recorded (:func:`_slot_read_back_empty_since_last_push`).
    """
    resolved = resolve_clear_failure(
        door_code=door_code,
        lock_entity_id=lock_entity_id,
        slot_index=slot_index,
        outcome=outcome,
        slot_empty=slot_empty,
    )
    if resolved is not None and (outcome in _SLOT_EMPTIED_OUTCOMES or slot_empty):
        return
    DoorCodeEvent.objects.create(
        door_code=door_code,
        user=door_code.user,
        lock_entity_id=lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_REMOVED,
        metadata={
            "action": _UNCONFIRMED_RESOLVED_ACTION,
            "slot_index": int(slot_index),
            "outcome": outcome,
            **({_SLOT_EMPTY_KEY: True} if slot_empty else {}),
        },
    )


def _clear_unconfirmed_slots_on_lock(
    *,
    door_code: DoorCode,
    pin: str,
    lock_entity_id: str,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float,
    skip_slots: set[int] | frozenset[int] = frozenset(),
) -> tuple[list[dict[str, object]], list[ClearFailure]]:
    """One lock's part of :func:`clear_unconfirmed_slots_holding_pin`; the caller holds its lock.

    Every slot it checks or clears is settled with :func:`_settle_unconfirmed_slot`,
    as is one on a lock latchpoint can't resolve any more (``lock_missing``), so
    later updates and deletes don't keep coming back to it (issue #161). A slot
    whose check or clear fails transiently stays unsettled. ``skip_slots`` are
    left alone, and so is a slot with no PIN to compare against. A
    ``slot_verified`` or ``slot_available`` attempt's slot is cleared when it
    reads back occupied with a masked code too (:func:`_read_back_attempt_slot`,
    issue #152). A slot that reads back empty is settled with ``slot_empty``,
    and one that answered empty once before it got no answer is recorded as a
    failure without those tags (PR #193 review).
    """
    cleared: list[dict[str, object]] = []
    failed: list[ClearFailure] = []
    attempts = {
        slot_index: attempted_pin
        for slot_index, attempted_pin in _unconfirmed_attempts(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            claimed_slots=_claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code),
        ).items()
        if slot_index not in skip_slots and (attempted_pin or pin)
    }
    if not attempts:
        return cleared, failed
    verified = _verified_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id)
    available = _available_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id)
    try:
        node_id = _resolve_lock_node_id(lock_entity_id=lock_entity_id)
    except Exception as exc:
        logger.warning("Can't resolve %s to check unconfirmed door code slots %s", lock_entity_id, list(attempts))
        for slot_index, attempted_pin in attempts.items():
            failure = record_clear_failure(
                door_code=door_code,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                exc=exc,
                expected_pin=attempted_pin or pin,
                unconfirmed=True,
                slot_verified=slot_index in verified,
                slot_available=slot_index in available,
            )
            failed.append(failure)
            if failure.permanent:
                _settle_unconfirmed_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
                )
        return cleared, failed
    for slot_index, attempted_pin in attempts.items():
        expected_pin = attempted_pin or pin
        try:
            verdict = _read_back_attempt_slot(
                zwavejs=zwavejs,
                node_id=node_id,
                slot_index=slot_index,
                pin=expected_pin,
                timeout_seconds=timeout_seconds,
                masked_counts=slot_index in verified or slot_index in available,
                disabled_masked_counts=slot_index in verified,
            )
            if verdict != _HOLDS_OURS:
                _settle_unconfirmed_slot(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    outcome="not_holding_pin",
                    slot_empty=verdict == _READ_BACK_EMPTY,
                )
                continue
            if slot_index in _claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code):
                # Another code took this slot during the readback, so what it holds is that code's PIN.
                _settle_unconfirmed_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="tracked"
                )
                continue
            clear_lock_user_code_slot(
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                zwavejs=zwavejs,
                timeout_seconds=timeout_seconds,
            )
            cleared.append({"lock_entity_id": lock_entity_id, "slot_index": slot_index})
            _settle_unconfirmed_slot(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="cleared"
            )
        except Exception as exc:
            logger.warning(
                "Could not check/clear unconfirmed slot %d on %s for door code id=%s; it may still hold the PIN",
                slot_index,
                lock_entity_id,
                door_code.id,
            )
            seen_empty = isinstance(exc, LockCodeUnverified) and exc.read_back_empty
            if seen_empty:
                # The retry reads it back again, but a masked code there isn't ours any more (PR #193 review).
                _record_slot_read_back_empty(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index)
            failure = record_clear_failure(
                door_code=door_code,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                exc=exc,
                expected_pin=expected_pin,
                unconfirmed=True,
                slot_verified=slot_index in verified and not seen_empty,
                slot_available=slot_index in available and not seen_empty,
            )
            failed.append(failure)
            if failure.permanent:
                _settle_unconfirmed_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
                )
    return cleared, failed


def inactive_slots_to_clear(
    *, door_code: DoorCode, failures: list[ClearFailure] | None = None
) -> list[tuple[str, int]]:
    """``(lock_entity_id, slot_index)`` pairs an inactive manual code may still have its PIN in (issue #158).

    That's its tracked slots, and the unconfirmed attempt slots on its locks that
    are still in their window and unsettled, skipping slots another code holds
    and slots with no PIN to compare against. Slots with an unresolved clear
    failure aren't listed, since :func:`retry_failed_slot_clears` handles those
    (pass ``failures`` when they're already loaded). Always empty for an active
    code, and for a synced one, whose slots are the lock's own.
    """
    if door_code.is_active or door_code.source == DoorCode.Source.SYNCED:
        return []
    return _slots_that_may_hold_pin(door_code=door_code, failures=failures)


def _slots_that_may_hold_pin(
    *, door_code: DoorCode, failures: list[ClearFailure] | None = None
) -> list[tuple[str, int]]:
    """The tracked and unconfirmed slots :func:`inactive_slots_to_clear` describes, for any code."""
    if failures is None:
        failures = unresolved_clear_failures(door_code=door_code)
    failing = {(f.lock_entity_id, f.slot_index) for f in failures}
    pin = decrypt_pin_or_none(door_code)
    slots: list[tuple[str, int]] = []
    assignments = (
        DoorCodeLockAssignment.objects.filter(door_code=door_code)
        .order_by("lock_entity_id")
        .values_list("lock_entity_id", "slot_index")
    )
    for lock_entity_id, tracked_slot in assignments:
        found = [int(tracked_slot)] if tracked_slot is not None else []
        attempts = _unconfirmed_attempts(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            claimed_slots=_claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code),
        )
        found.extend(slot_index for slot_index, attempted_pin in attempts.items() if attempted_pin or pin)
        slots.extend(
            (lock_entity_id, slot_index)
            for slot_index in dict.fromkeys(found)
            if (lock_entity_id, slot_index) not in failing
        )
    return slots


def pending_slot_clears(*, door_code: DoorCode, failures: list[ClearFailure] | None = None) -> list[dict[str, object]]:
    """The slot clears still outstanding for ``door_code``, for the API (issue #151). Never includes a PIN.

    Its unresolved clear failures, plus for an inactive manual code the slots
    :func:`inactive_slots_to_clear` finds, which the scheduler and Retry will
    clear. Sorted by lock and slot.
    """
    if failures is None:
        failures = unresolved_clear_failures(door_code=door_code)
    entries = {
        (f.lock_entity_id, f.slot_index): {
            "lock_entity_id": f.lock_entity_id,
            "slot_index": f.slot_index,
            "removing": f.removing,
        }
        for f in failures
    }
    for lock_entity_id, slot_index in inactive_slots_to_clear(door_code=door_code, failures=failures):
        entries.setdefault(
            (lock_entity_id, slot_index),
            {"lock_entity_id": lock_entity_id, "slot_index": slot_index, "removing": False},
        )
    return [entries[key] for key in sorted(entries)]


def _tracked_slot_may_hold_pin(
    *, zwavejs: ZwavejsGateway, lock_entity_id: str, slot_index: int, pin: str | None, timeout_seconds: float
) -> bool:
    """Read a slot an inactive code tracks back before clearing it (PR #167 review).

    ``True`` when it holds ``pin`` (enabled or disabled), or reads back occupied
    with a code that can't be read, which counts as this code's since it tracks
    the slot. ``False`` when it holds a different readable code (ie one typed in
    on the keypad since) or reads back empty. A code whose own PIN can't be read
    has nothing to compare against, so its slot counts as its own.
    :class:`LockCodeUnverified` and gateway errors propagate.
    """
    if not pin:
        return True
    try:
        _verify_user_code_slot(
            zwavejs=zwavejs,
            node_id=_resolve_lock_node_id(lock_entity_id=lock_entity_id),
            slot_index=slot_index,
            pin=pin,
            timeout_seconds=timeout_seconds,
        )
    except LockRejectedCode as exc:
        if exc.holds_pin:
            return True
        # A different code, or empty (the only rejection that asks for a clear
        # without holding the PIN). Disabled with an unreadable code stays ours.
        return not (exc.holds_other or exc.clear_slot)
    return True


def _clear_inactive_slots_on_lock(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float,
) -> list[ClearFailure]:
    """One lock's part of :func:`clear_inactive_code_slots`; the caller holds its lock."""
    failing = {
        f.slot_index for f in unresolved_clear_failures(door_code=door_code) if f.lock_entity_id == lock_entity_id
    }
    pin = decrypt_pin_or_none(door_code)
    failed: list[ClearFailure] = []
    assignment = DoorCodeLockAssignment.objects.filter(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index__isnull=False
    ).first()
    holds_pin: bool | None = None
    if assignment is not None and assignment.slot_index not in failing:
        slot_index = int(assignment.slot_index)
        try:
            holds_pin = _tracked_slot_may_hold_pin(
                zwavejs=zwavejs,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                pin=pin,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            # Not recorded: a recorded failure on a tracked slot is retried as a
            # clear with no readback, so this one stays a slot to read back first.
            failure = describe_clear_failure(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, exc=exc
            )
            failed.append(failure)
            if failure.permanent:
                forget_cleared_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
                )
        if holds_pin is False:
            # Someone typed another code into it, or it's empty: nothing of ours to clear.
            forget_cleared_slot(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="not_holding_pin"
            )
    if holds_pin:
        slot_index = int(assignment.slot_index)
        try:
            clear_lock_user_code_slot(
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                zwavejs=zwavejs,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            failure = record_clear_failure(
                door_code=door_code,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                exc=exc,
                expected_pin=pin,
            )
            failed.append(failure)
            if failure.permanent:
                forget_cleared_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
                )
        else:
            forget_cleared_slot(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="cleared"
            )
    _, unconfirmed_failed = _clear_unconfirmed_slots_on_lock(
        door_code=door_code,
        pin=pin or "",
        lock_entity_id=lock_entity_id,
        zwavejs=zwavejs,
        timeout_seconds=timeout_seconds,
        skip_slots=failing,
    )
    failed.extend(unconfirmed_failed)
    return failed


def clear_inactive_code_slots(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 5.0,
) -> list[ClearFailure]:
    """Clear the slots :func:`inactive_slots_to_clear` finds, for the scheduler and Retry (issue #158).

    A slot the code tracks is read back first, since nothing has written to it
    for a while (ie rows from before #144) and a keypad code may have replaced
    the PIN: it's cleared when it holds this code's PIN or a code that can't be
    read, and forgotten without a clear when it holds a different code or reads
    back empty (:func:`_tracked_slot_may_hold_pin`). A readback that gets no
    answer isn't recorded, so the next try reads it back again. An unconfirmed
    slot is read back and only cleared when it holds the PIN that attempt sent,
    then settled (:func:`_clear_unconfirmed_slots_on_lock`). A slot another code
    holds is never touched. A clear that fails is recorded with
    :func:`record_clear_failure` so :func:`retry_failed_slot_clears` takes over.
    Either failure counts toward the attempt cap. A lock latchpoint can't
    resolve any more is settled as ``lock_missing``.

    Each lock is handled while holding its ``lock_sync:`` lock (one deadline
    shared across them), and the code is read again once it's held, so a code
    turned back on or deleted meanwhile is left alone. Returns the clears still
    outstanding, including those on a lock still busy at the deadline, which
    don't count toward the cap since nothing was tried there.
    """
    still_failing: list[ClearFailure] = []
    attempted_and_failed = False
    deadline = sync_lock_deadline()
    slots = inactive_slots_to_clear(door_code=door_code)
    for lock_entity_id in sorted({lock for lock, _slot in slots}):
        try:
            with hold_lock_sync([lock_entity_id], deadline=deadline):
                try:
                    door_code.refresh_from_db(fields=["is_active", "source", "encrypted_pin"])
                except DoorCode.DoesNotExist:
                    return still_failing
                if door_code.is_active or door_code.source == DoorCode.Source.SYNCED:
                    return still_failing
                failed = _clear_inactive_slots_on_lock(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    zwavejs=zwavejs,
                    timeout_seconds=timeout_seconds,
                )
        except LockBusy as exc:
            logger.warning(
                "Skipping the slot clears on %s for inactive door code id=%s: %s", lock_entity_id, door_code.id, exc
            )
            still_failing.extend(
                ClearFailure(lock_entity_id=lock, slot_index=slot_index, reason=_clear_error_reason(exc))
                for lock, slot_index in slots
                if lock == lock_entity_id
            )
            continue
        transient = [f for f in failed if not f.permanent]
        still_failing.extend(transient)
        attempted_and_failed = attempted_and_failed or bool(transient)

    if attempted_and_failed:
        door_code.refresh_from_db(fields=["push_attempt_count"])
        door_code.push_attempt_count = (door_code.push_attempt_count or 0) + 1
        door_code.last_push_attempt_at = django_timezone.now()
        door_code.save(update_fields=["push_attempt_count", "last_push_attempt_at", "updated_at"])
    return still_failing


def slots_to_withdraw(*, door_code: DoorCode) -> list[tuple[str, int]]:
    """``(lock_entity_id, slot_index)`` pairs an active code may have its PIN in before its start (issue #145).

    The same slots :func:`inactive_slots_to_clear` finds for an inactive code:
    tracked ones and unsettled unconfirmed ones, without slots another code
    holds or that already have a clear failure on record for the retries.
    """
    if not door_code.is_active:
        return []
    return _slots_that_may_hold_pin(door_code=door_code)


def withdraw_slots_before_start(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 5.0,
) -> tuple[list[dict[str, object]], list[ClearFailure]]:
    """Clear what :func:`slots_to_withdraw` finds; the caller holds every lock's ``lock_sync:`` lock.

    A tracked slot is cleared as is and forgotten, the way a schedule change
    clears it before the re-push. An unconfirmed slot is read back and only
    cleared when it holds the PIN that attempt sent, then settled
    (:func:`_clear_unconfirmed_slots_on_lock`). A clear that fails is recorded
    with :func:`record_clear_failure` so :func:`retry_failed_slot_clears` takes
    over, and a lock latchpoint can't resolve any more is forgotten as
    ``lock_missing``. Returns the slots cleared and the failures.
    """
    failing = {(f.lock_entity_id, f.slot_index) for f in unresolved_clear_failures(door_code=door_code)}
    pin = decrypt_pin_or_none(door_code)
    cleared: list[dict[str, object]] = []
    failed: list[ClearFailure] = []
    assignments = DoorCodeLockAssignment.objects.filter(door_code=door_code).order_by("lock_entity_id")
    for lock_entity_id, tracked_slot in assignments.values_list("lock_entity_id", "slot_index"):
        if tracked_slot is not None and (lock_entity_id, int(tracked_slot)) not in failing:
            slot_index = int(tracked_slot)
            try:
                clear_lock_user_code_slot(
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    zwavejs=zwavejs,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                failure = record_clear_failure(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    exc=exc,
                    expected_pin=pin,
                )
                failed.append(failure)
                if failure.permanent:
                    forget_cleared_slot(
                        door_code=door_code,
                        lock_entity_id=lock_entity_id,
                        slot_index=slot_index,
                        outcome="lock_missing",
                    )
            else:
                cleared.append({"lock_entity_id": lock_entity_id, "slot_index": slot_index})
                forget_cleared_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="cleared"
                )
        lock_cleared, lock_failed = _clear_unconfirmed_slots_on_lock(
            door_code=door_code,
            pin=pin or "",
            lock_entity_id=lock_entity_id,
            zwavejs=zwavejs,
            timeout_seconds=timeout_seconds,
            skip_slots={slot for lock, slot in failing if lock == lock_entity_id},
        )
        cleared.extend(lock_cleared)
        failed.extend(lock_failed)
    return cleared, failed


def retained_marker_event_ids(*, older_than: datetime) -> set[int]:
    """Ids of events older than ``older_than`` that event retention must keep (issue #139).

    Those are a code's unresolved ``clear_failed`` events (the newest per slot,
    which carries its flags and expected PIN) and its unsettled
    ``push_unconfirmed`` events (the newest per slot still in the window since
    its last successful push to that lock). Pruning either would forget a slot
    that may still hold a PIN. Settled markers, including attempts a cleanup has
    checked or cleared (issue #161), and markers whose code is gone, aren't kept.

    Also kept is every ``slot_empty`` marker, from any code, newer than a kept
    ``slot_verified`` or ``slot_available`` attempt or failure on the same lock
    and slot, since pruning it would bring back that record's masked-slot trust
    (PR #193 review, :func:`_masked_trust_dropped`).
    """
    old_markers = DoorCodeEvent.objects.filter(
        created_at__lt=older_than,
        door_code__isnull=False,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata__action__in=[_CLEAR_FAILED_ACTION, _UNCONFIRMED_PUSH_ACTION],
    )
    keep: set[int] = set()
    for door_code in DoorCode.objects.filter(id__in=old_markers.values("door_code_id")):
        keep.update(f.event_id for f in unresolved_clear_failures(door_code=door_code) if f.event_id is not None)
        lock_entity_ids = (
            old_markers.filter(door_code=door_code, metadata__action=_UNCONFIRMED_PUSH_ACTION)
            .values_list("lock_entity_id", flat=True)
            .distinct()
        )
        for lock_entity_id in lock_entity_ids:
            keep.update(
                event_id
                for event_id, _metadata in _unsettled_unconfirmed_attempts(
                    door_code=door_code, lock_entity_id=lock_entity_id
                ).values()
            )
    keep.update(_slot_empty_markers_disarming(kept_ids=keep, older_than=older_than))
    return keep


def _slot_empty_markers_disarming(*, kept_ids: set[int], older_than: datetime) -> set[int]:
    """Ids of ``slot_empty`` markers older than ``older_than`` newer than a kept tagged record on their slot."""
    oldest_tagged: dict[tuple[str, int], int] = {}
    kept = DoorCodeEvent.objects.filter(id__in=kept_ids).values_list("id", "lock_entity_id", "metadata")
    for event_id, lock_entity_id, metadata in kept:
        if not isinstance(metadata, dict):
            continue
        if not (metadata.get(_SLOT_VERIFIED_KEY) or metadata.get(_SLOT_AVAILABLE_KEY)):
            continue
        slot_index = _coerce_int(metadata.get("slot_index"))
        if slot_index is None:
            continue
        key = (lock_entity_id, slot_index)
        oldest_tagged[key] = min(oldest_tagged.get(key, event_id), event_id)
    markers: set[int] = set()
    for (lock_entity_id, slot_index), since_id in oldest_tagged.items():
        markers.update(
            _slot_empty_marker_events()
            .filter(
                created_at__lt=older_than,
                lock_entity_id=lock_entity_id,
                metadata__slot_index=slot_index,
                id__gt=since_id,
            )
            .values_list("id", flat=True)
        )
    return markers


def _clear_slot_best_effort(
    *,
    zwavejs: ZwavejsGateway,
    lock_entity_id: str,
    slot_index: int,
    timeout_seconds: float,
) -> None:
    """Clear a slot we just wrote whose readback rejected the code; failures are only logged.

    Safe because the slot was free when this push picked it.
    """
    try:
        clear_lock_user_code_slot(
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            zwavejs=zwavejs,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        logger.warning(
            "Could not clear slot %d on %s after the lock rejected the code; it may still hold the PIN",
            slot_index,
            lock_entity_id,
            exc_info=True,
        )


# CC 78 daily-repeating schedules are time-based, so "all day" is the widest
# expressible window: 00:00 for 23h59m. Used when a code restricts days but
# carries no explicit time-of-day window.
_FULL_DAY_START = time(0, 0)
_FULL_DAY_DURATION = (23, 59)


def _compute_schedule_duration(window_start: time, window_end: time) -> tuple[int, int]:
    """Return (durationHour, durationMinute) for a same-day window."""
    start_dt = datetime(2000, 1, 1, window_start.hour, window_start.minute, tzinfo=timezone.utc)
    end_dt = datetime(2000, 1, 1, window_end.hour, window_end.minute, tzinfo=timezone.utc)
    if end_dt <= start_dt:
        raise InvalidPin("Schedule window_end must be after window_start (same-day).")
    delta: timedelta = end_dt - start_dt
    total_minutes = int(delta.total_seconds() // 60)
    return total_minutes // 60, total_minutes % 60


def _validate_schedule_or_raise(door_code: DoorCode) -> None:
    """Raise :class:`InvalidPin` when :func:`_push_daily_repeating_schedule` would reject the code's window.

    Checked before the ``set`` (issue #123), so a window that got past the
    serializer fails before the PIN is on the lock instead of after it. Same
    conditions as the schedule push: no ``days_of_week`` means no schedule, and
    a missing start or end falls back to the full day.
    """
    if door_code.days_of_week is None or not (door_code.window_start and door_code.window_end):
        return
    _compute_schedule_duration(door_code.window_start, door_code.window_end)


def _push_daily_repeating_schedule(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    slot_index: int,
    door_code: DoorCode,
    timeout_seconds: float,
) -> list[int]:
    """Push CC 78 daily-repeating schedule for each enabled weekday. Returns ZW weekday ints used.

    When the code restricts days but carries no time-of-day window, the schedule
    falls back to a full-day window (00:00 + 23h59m) so the day restriction still
    reaches the lock. The stored model is not mutated — synthesis happens here only.
    """
    if door_code.days_of_week is None:
        return []

    if door_code.window_start and door_code.window_end:
        start = door_code.window_start
        duration_h, duration_m = _compute_schedule_duration(start, door_code.window_end)
    else:
        start = _FULL_DAY_START
        duration_h, duration_m = _FULL_DAY_DURATION
    if duration_h == 0 and duration_m == 0:
        return []

    weekdays_pushed: list[int] = []
    for bit, zwave_weekday in _WEEKDAY_BIT_TO_ZWAVE.items():
        if not (int(door_code.days_of_week) & (1 << bit)):
            continue
        slot_id = bit + 1
        # setDailyRepeatingSchedule(slot, schedule) — two positional args.
        slot = {"userId": slot_index, "slotId": slot_id}
        schedule = {
            "weekdays": [zwave_weekday],
            "startHour": start.hour,
            "startMinute": start.minute,
            "durationHour": duration_h,
            "durationMinute": duration_m,
        }
        zwavejs.invoke_cc_api(
            node_id=node_id,
            command_class=CC_SCHEDULE_ENTRY_LOCK,
            method_name="setDailyRepeatingSchedule",
            args=[slot, schedule],
            timeout_seconds=timeout_seconds,
        )
        weekdays_pushed.append(zwave_weekday)
    return weekdays_pushed


# Mask any run of 4–8 consecutive digits in stored error strings. PINs in this
# system are 4–8 digits; slot indices (1–99) and node IDs (1–232) are 1–3 digits;
# HTTP status codes are 3 digits; ZJS home_ids are 10+ digits — so this band
# masks accidental PIN leaks without scrubbing useful diagnostic numbers.
_PIN_LIKE_DIGIT_RUN = re.compile(r"(?<!\d)\d{4,8}(?!\d)")


def sanitize_push_error_for_storage(message: str | None) -> str:
    """Return ``message`` with any 4–8-digit run replaced by ``****``.

    Defense-in-depth against a future gateway / exception class that includes
    user-supplied data in its ``__str__``: keeps PIN material out of
    ``DoorCode.last_push_error`` and ``DoorCodeEvent.metadata`` even if upstream
    error messages start carrying it.
    """
    if not message:
        return ""
    return _PIN_LIKE_DIGIT_RUN.sub("****", str(message))


def _stamp_push_attempt(*, door_code: DoorCode, at: datetime) -> None:
    """Take the code row and stamp its ``last_push_attempt_at``; the caller holds a transaction.

    Kept on every push attempt, since ``enforce_door_code_validity``'s
    ``just_started`` pass reads it (PR #183).
    """
    _lock_code_row(door_code.id)
    DoorCode.objects.filter(id=door_code.id).update(last_push_attempt_at=at, updated_at=at)
    door_code.last_push_attempt_at = at


def _record_lock_push_failure(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    error_message: str,
    terminal: bool,
    event_metadata: dict[str, object] | None = None,
    counted: bool = True,
) -> None:
    """Record a push failure on this lock, then refresh the code (issue #126).

    A transient failure leaves the lock ``pending`` and a terminal one makes it
    ``failed``. Either way the attempt is counted on the lock (the code-level
    count only counts clear retries now, and PR #192 counts a terminal
    ``InvalidPin``), unless ``counted`` is off for a push that ran out of its
    time budget (issue #124), and it gets the error and the attempt time. Only a lock that still needs a
    push is written: no slot, or a slot whose schedule is pending (issue #123),
    which it keeps. A pushed lock is left alone (the node lookup records its
    failure before the push checks for a slot). The code-level
    ``last_push_attempt_at`` is stamped, the code row first and the code
    refreshed in the same transaction, so a reader never sees the lock
    ``failed`` without the code's rollup. A terminal failure adds a
    ``code_failed`` event with the lock in ``lock_entity_id`` and
    ``event_metadata``.
    """
    safe_message = sanitize_push_error_for_storage(error_message)
    attempted_at = django_timezone.now()
    with transaction.atomic():
        _stamp_push_attempt(door_code=door_code, at=attempted_at)
        DoorCodeLockAssignment.objects.filter(door_code=door_code, lock_entity_id=lock_entity_id).filter(
            Q(slot_index__isnull=True) | Q(schedule_pending=True)
        ).update(
            push_state=DoorCode.PushState.FAILED if terminal else DoorCode.PushState.PENDING,
            push_attempt_count=F("push_attempt_count") + (1 if counted else 0),
            last_push_error=_cut_push_error(safe_message),
            last_push_attempt_at=attempted_at,
        )
        refresh_push_state(door_code=door_code)

    if terminal:
        DoorCodeEvent.objects.create(
            door_code=door_code,
            user=door_code.user,
            lock_entity_id=lock_entity_id,
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata={"action": "push", "reason": safe_message[:200], **(event_metadata or {})},
        )


def _fail_slot_recorded_for_another_code(
    *, door_code: DoorCode, lock_entity_id: str, slot_index: int
) -> LockPushFailed:
    """Record the push whose slot write hit ``door_code_lock_assignments_unique_lock_slot`` (issues #109, #129).

    The lock may now hold this PIN in ``slot_index`` in place of the code the DB
    has there, so the error and the ``code_failed`` event name that code and say
    what to do next (also kept whole in the event's ``next_step``, since its
    ``reason`` is cut at 200 characters). A code lock sync imported gets its PIN
    from whatever the slot holds on the next sync, so for one of those the next
    step is dropping this lock from this code once the sync reports the slot
    holding this PIN (its duplicate PIN flag), rather than a retry that would
    put it in a second slot.

    The ``push_unconfirmed`` attempt the push recorded for the slot right before
    its write stays, with this PIN, since the delete of it rolled back with the
    write. Every cleanup and
    adoption skips a slot another code holds, so it does nothing while that code
    has it, but if that code lets go of the slot without clearing it (ie a
    readback found this PIN there instead of its own), a delete or deactivate of
    this code reads it back and clears it, and a retry adopts it.
    """
    owner = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(lock_entity_id=lock_entity_id, slot_index=slot_index)
        .exclude(door_code=door_code)
        .first()
    )
    owner_code = owner.door_code if owner is not None else None
    if owner_code is None:
        holder = "another door code"
        in_place_of = "the code recorded there"
    else:
        label = f', "{owner_code.label}"' if owner_code.label else ""
        holder = f"another door code (id {owner_code.id}{label})"
        in_place_of = "that code's"
    if owner_code is not None and owner_code.source == DoorCode.Source.SYNCED:
        next_step = (
            f"That code was imported by a lock sync, so the next lock sync on {lock_entity_id} gives it "
            f"whatever PIN slot {slot_index} holds. Run one, and if it reports slot {slot_index} holding this "
            f"code's PIN, remove {lock_entity_id} from this code instead of retrying, since a retry puts the PIN "
            "in a second slot."
        )
    else:
        next_step = f"Run a lock sync on {lock_entity_id} to check what the slot holds before retrying."
    message = (
        f"Slot {slot_index} on {lock_entity_id} was recorded for {holder} during the push. "
        f"The lock may now hold this PIN in slot {slot_index} in place of {in_place_of}. {next_step}"
    )
    _record_lock_push_failure(
        door_code=door_code,
        error_message=message,
        terminal=True,
        lock_entity_id=lock_entity_id,
        event_metadata={
            "slot_index": int(slot_index),
            "conflicting_door_code_id": owner_code.id if owner_code is not None else None,
            "conflicting_door_code_label": owner_code.label if owner_code is not None else None,
            "conflicting_door_code_source": owner_code.source if owner_code is not None else None,
            "lock_sync_needed": True,
            "next_step": sanitize_push_error_for_storage(next_step),
        },
    )
    return LockPushFailed(sanitize_push_error_for_storage(message))


def push_door_code_to_lock(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    zwavejs: ZwavejsGateway,
    actor_user=None,
    timeout_seconds: float = 5.0,
) -> PushResult:
    """Program ``door_code``'s PIN onto ``lock_entity_id``.

    Allocates the lowest-free slot, sends CC 99 ``set`` (and CC 78 schedule when
    the code carries a daily window), and persists the slot index + push state.
    If an earlier push of this code sent the PIN to a slot on this lock but
    couldn't confirm it, and that slot now reads back with the PIN, the slot is
    adopted instead of writing a new one.

    Errors:
      * :class:`InvalidPin` / :class:`LockSlotsFull` raise before any ``set``.
        :class:`InvalidPin` (a PIN that can't be read, or a schedule window
        that ends before it starts) is recorded as a terminal failure on this
        lock, since only an edit fixes it (issue #123). :class:`LockSlotsFull`
        is recorded as a transient failure, so the row stays ``pending`` and
        the scheduler's attempt cap applies.
      * :class:`LockRejectedCode` — terminal; the lock answered the ``set``
        with a Supervision Fail (no readback then), or the post-set readback
        shows it didn't store the PIN. The lock is flipped to ``failed``. When
        the PIN didn't land and it matches the admin code Z-Wave JS has cached,
        the error says it may match the lock's admin code (issue #125).
      * :class:`LockUnreachable` — transient; the row stays ``pending`` and the
        scheduler will retry.
      * :class:`LockPushFailed` — terminal; the row is flipped to ``failed`` and a
        ``code_failed`` event is emitted.
      * :class:`PushSuperseded` — once the lock is held the code turns out to be
        deleted, inactive, no longer on this lock, not started yet or expired
        (issue #145); nothing is sent or recorded.

    The code's PIN, schedule and assignment are read again once the
    ``lock_sync:`` lock is held, since a caller that loaded them earlier (the
    scheduler) may have waited behind an update or delete (issue #131). An
    assignment that has a slot by then is returned as is instead of being
    written to a second slot.

    Has to run in autocommit, so the slot is committed before the lock is let go
    (issue #130). Called inside a caller's transaction it raises
    :class:`PushInTransaction` in dev and tests and logs a warning in prod.
    """
    _check_no_outer_transaction(door_code=door_code, lock_entity_id=lock_entity_id)
    try:
        node_id = _resolve_lock_node_id(lock_entity_id=lock_entity_id)
    except (LockSyncNotFound, LockSyncInvalidRequest) as exc:
        # Terminal config issue: the Entity row exists but has no usable Z-Wave JS
        # node_id (or the entity itself is missing). Operator must sync HA entities
        # first; retries will just rediscover the same problem. Record + flip the
        # row to FAILED so the UI surfaces last_push_error instead of stalling on
        # "pending sync" forever.
        _record_lock_push_failure(
            door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id
        )
        raise LockPushFailed(str(exc)) from exc

    lock_key = f"lock_sync:{lock_entity_id}"
    acquired, lock_id = _try_acquire_sync_lock(lock_key=lock_key)
    if not acquired:
        raise LockUnreachable("Another sync is in progress for this lock; will retry.")

    try:
        try:
            door_code.refresh_from_db(fields=[*_PUSHED_FIELDS, *_VALIDITY_FIELDS])
        except DoorCode.DoesNotExist as exc:
            raise PushSuperseded("Door code was deleted before its push started.") from exc
        assignment = DoorCodeLockAssignment.objects.filter(door_code=door_code, lock_entity_id=lock_entity_id).first()
        if not door_code.is_active or assignment is None:
            raise PushSuperseded("Door code is no longer active on this lock; nothing was pushed.")
        if not belongs_on_lock(door_code):
            # Its start_at moved into the future or it expired while the push waited (issue #145).
            raise PushSuperseded("Door code isn't valid right now (not started or expired); nothing was pushed.")
        if lock_entity_id in _locks_being_removed(door_code=door_code):
            # Being dropped from this lock while its clear keeps failing (issue #151).
            raise PushSuperseded("Door code is being removed from this lock; nothing was pushed.")
        if assignment.slot_index is not None:
            if assignment.schedule_pending:
                if _unresolved_clear_failure(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=int(assignment.slot_index)
                ):
                    # A PIN change's clear of this slot failed, so it may still hold
                    # the old PIN. Sending the schedule would give that PIN the new
                    # window. The clear retry frees the slot and the code is pushed
                    # there fresh (PR #196 review). Nothing sent, nothing counted.
                    raise LockUnreachable("This slot still has a clear outstanding; the schedule waits for it.")
                # The PIN is in the slot already, only its schedule is missing (issue #123).
                return _push_pending_schedule(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    node_id=node_id,
                    slot_index=int(assignment.slot_index),
                    zwavejs=zwavejs,
                    actor_user=actor_user,
                    timeout_seconds=timeout_seconds,
                )
            logger.info(
                "Door code id=%d already holds slot %d on %s; not pushing it again",
                door_code.id,
                assignment.slot_index,
                lock_entity_id,
            )
            return PushResult(lock_entity_id=lock_entity_id, node_id=node_id, slot_index=int(assignment.slot_index))
        try:
            pin = _decrypt_pin_or_raise(door_code)
            _validate_schedule_or_raise(door_code)
        except InvalidPin as exc:
            # Only an edit fixes the stored PIN or window, so this is terminal for
            # the lock: recorded and counted instead of pushed again every tick,
            # and nothing goes out, so a bad window never leaves an unscheduled PIN
            # on the lock (issue #123). Checked here, with the lock held and the
            # code read again, so a stale copy can't mark a fixed code failed.
            _record_lock_push_failure(
                door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id
            )
            raise

        claimed_slots = _claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code)
        # Once per push, for the free-slot search and the admin code hint (issue #124).
        get_value_ids = _defined_value_ids_once(zwavejs=zwavejs, node_id=node_id, timeout_seconds=timeout_seconds)
        try:
            # No admin code check here: Z-Wave JS's cached adminCode can be stale,
            # and a stale one would fail the code for good with nothing sent. The
            # readback decides, and the cache only explains a rejection (issue #125).
            adoptable = _find_adoptable_attempted_slot(
                zwavejs=zwavejs,
                node_id=node_id,
                door_code=door_code,
                lock_entity_id=lock_entity_id,
                pin=pin,
                timeout_seconds=timeout_seconds,
                claimed_slots=claimed_slots,
            )
            slot_index, resend_to_attempted_slot = adoptable if adoptable is not None else (None, False)
            # A resend goes through the set and readback like a new slot (issue #128).
            adopted_existing_slot = slot_index is not None and not resend_to_attempted_slot
            if slot_index is None:
                slot_index = _enumerate_free_slot(
                    zwavejs=zwavejs,
                    node_id=node_id,
                    timeout_seconds=timeout_seconds,
                    value_ids=get_value_ids(),
                    claimed_slots=claimed_slots,
                )
        except (ZwavejsNotConfigured, ZwavejsClientUnavailable, ZwavejsCommandValidationError) as exc:
            _record_lock_push_failure(
                door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id
            )
            raise LockPushFailed(str(exc)) from exc
        except LockSlotsFull as exc:
            # Counted like any transient failure, so a lock with nothing Available
            # ends up failed at the attempt cap instead of retried forever.
            _record_lock_push_failure(
                door_code=door_code,
                error_message=str(exc),
                terminal=False,
                lock_entity_id=lock_entity_id,
                counted=not _out_of_budget(zwavejs),
            )
            raise
        except LockRejectedCode as exc:
            _record_lock_push_failure(
                door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id
            )
            raise
        except LockPushFailed:
            raise
        except GatewayError as exc:
            # Out of time isn't counted toward the cap (issue #124).
            _record_lock_push_failure(
                door_code=door_code,
                error_message=f"{exc.__class__.__name__}: {exc}",
                terminal=False,
                lock_entity_id=lock_entity_id,
                counted=not _out_of_budget(zwavejs),
            )
            raise LockUnreachable("Lock is not reachable right now; will retry.") from exc

        logger.info(
            "%s door code id=%d to %s (node=%d slot=%d)",
            "Adopting existing slot for"
            if adopted_existing_slot
            else "Re-sending to the attempted slot"
            if resend_to_attempted_slot
            else "Pushing",
            door_code.id,
            lock_entity_id,
            node_id,
            slot_index,
        )

        # Once the PIN may be in the slot (set sent, or slot adopted), a gateway
        # failure, transient or a terminal Z-Wave JS one, records the slot so the
        # retry can adopt it instead of writing the PIN to a second slot.
        pin_sent_to_slot = adopted_existing_slot
        # The set returned (or the slot was adopted). The terminal Z-Wave JS errors
        # below are raised before anything is sent, so one from the set itself
        # means the PIN never went out, and one after it means it did.
        set_returned = adopted_existing_slot
        # Whether a readback in this push accepted the slot: the post-set one, or
        # the adoption readback for an adopted slot.
        slot_accepted = adopted_existing_slot
        try:
            if not adopted_existing_slot:
                pin_sent_to_slot = True
                # Z-Wave JS CC 99 set signature is (userId, userIdStatus, userCode).
                # userIdStatus = 1 means "Occupied" (the code is active on the lock).
                # The server validator rejects 2-arg calls; passing only [slot, pin]
                # makes the PIN land where userIdStatus is expected.
                set_result = zwavejs.invoke_cc_api(
                    node_id=node_id,
                    command_class=CC_USER_CODE,
                    method_name="set",
                    args=[slot_index, 1, pin],
                    timeout_seconds=timeout_seconds,
                )
                set_returned = True
                if _supervision_status(set_result) == _SUPERVISION_STATUS_FAIL:
                    # The lock says it didn't carry out the set, so the push takes
                    # that as a rejection with no readback (issue #125). The handler
                    # below still keeps the slot on record in case the lock lied.
                    # A supervised Success or no result still goes to the readback
                    # below, since a lock can say Success and drop the code.
                    raise LockRejectedCode(
                        f"Lock rejected the code for slot {slot_index} (Supervision reported Fail).",
                        supervision_failed=True,
                    )
                # The set returning is not proof the lock kept the code (issue #107);
                # read the slot back before claiming it or pushing schedules to it.
                # That get also makes Z-Wave JS re-read the slot, so it doubles as
                # the cache refresh #106 added; no second get after the success stamp.
                _verify_user_code_slot(
                    zwavejs=zwavejs,
                    node_id=node_id,
                    slot_index=slot_index,
                    pin=pin,
                    timeout_seconds=timeout_seconds,
                )
                slot_accepted = True
            # The schedule goes out once the slot is on record (issue #123), below.
        except (ZwavejsNotConfigured, ZwavejsClientUnavailable, ZwavejsCommandValidationError) as exc:
            if set_returned:
                # The PIN may be in the slot, so keep it on record like a transient
                # failure does, or nothing would clear it on a delete (PR #192).
                # Tagged slot_verified only once a readback accepted the slot, so a
                # masked readback later counts as ours only then. Never
                # slot_available here, since what the readback saw before the
                # error isn't known (issue #128).
                _record_unconfirmed_slot_attempt(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    reason=f"{exc.__class__.__name__}: {exc}",
                    pin=pin,
                    slot_verified=slot_accepted,
                )
            _record_lock_push_failure(
                door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id
            )
            raise LockPushFailed(str(exc)) from exc
        except LockRejectedCode as exc:
            if exc.clear_slot and not exc.holds_pin:
                # Read back empty after the set, so whatever earlier attempts of
                # this code left in the slot is gone, and a later unconfirmed set
                # there doesn't count a masked readback as ours (issue #128).
                _settle_unconfirmed_slot(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    outcome="not_holding_pin",
                    slot_empty=True,
                )
            if exc.clear_slot:
                _clear_slot_best_effort(
                    zwavejs=zwavejs,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    timeout_seconds=timeout_seconds,
                )
            event_metadata: dict[str, object] = {}
            if exc.supervision_failed:
                event_metadata.update(slot_index=int(slot_index), supervision_status="fail")
                # In case the lock stored the PIN anyway, so a delete, deactivate or
                # PIN change reads the slot back and clears it. A set into a freshly
                # picked slot leaves it untagged: nothing has seen the PIN there, so
                # only a readback showing this exact readable PIN counts the slot as
                # ours (for those cleanups and for adoption on Retry), and a masked
                # slot, maybe a keypad code typed in there, is left alone (#193's
                # rules). A resend keeps the trust of the tagged attempt it went to,
                # since this marker becomes the newest one for the slot and an
                # untagged one would leave the earlier PIN there on a delete (PR #198
                # review). The slot_available tag is still dropped if this code read
                # the slot back empty since its last push. That trust is only ever
                # slot_available: _find_adoptable_attempted_slot adopts a
                # slot_verified attempt with this PIN instead of resending to it.
                _record_unconfirmed_slot_attempt(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    reason="Lock answered the set with Supervision Fail",
                    pin=pin,
                    slot_available=resend_to_attempted_slot,
                )
            # The lock turned the PIN down (Supervision Fail, or the slot read back
            # empty). Still terminal with an admin code match, like without one: the
            # lock's answer decides, the cache only explains it, so a stale cache
            # can't keep a PIN off a lock that takes it (issue #125).
            if (exc.supervision_failed or (exc.clear_slot and not exc.holds_pin)) and _pin_may_match_admin_code(
                zwavejs=zwavejs, node_id=node_id, pin=pin, timeout_seconds=timeout_seconds, get_value_ids=get_value_ids
            ):
                exc.args = (_with_admin_code_hint(str(exc)),)
                event_metadata["may_match_admin_code"] = True
            _record_lock_push_failure(
                door_code=door_code,
                error_message=str(exc),
                terminal=True,
                lock_entity_id=lock_entity_id,
                event_metadata=event_metadata or None,
            )
            raise
        except GatewayError as exc:
            error_message = f"{exc.__class__.__name__}: {exc}"
            if isinstance(exc, TimeBudgetExceeded) and not set_returned:
                # The budget refused the set itself, so nothing went to the slot (issue #124).
                pin_sent_to_slot = False
            if (
                isinstance(exc, LockCodeUnverified)
                and exc.read_back_empty
                and _pin_may_match_admin_code(
                    zwavejs=zwavejs,
                    node_id=node_id,
                    pin=pin,
                    timeout_seconds=timeout_seconds,
                    get_value_ids=get_value_ids,
                )
            ):
                # One empty answer and then silence is no verdict, so this stays
                # transient, but the hint goes with it (issue #125).
                error_message = _with_admin_code_hint(error_message)
            if pin_sent_to_slot and isinstance(exc, LockCodeUnverified) and exc.read_back_empty:
                # Drops the masked-slot trust of anything else on record for this slot (PR #193 review).
                _record_slot_read_back_empty(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index)
            if pin_sent_to_slot:
                # Tagged like the terminal branch above: only once a readback in
                # this push accepted the slot (an adopted slot). Since the schedule
                # moved after the slot write that can't happen here any more, but
                # the rule stands. Otherwise the set went into a slot that was Available when it was
                # picked (enumerated, or a resend to a slot_available attempt), so
                # it's slot_available unless a readback answered empty (issue #128).
                _record_unconfirmed_slot_attempt(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    reason=error_message,
                    pin=pin,
                    slot_verified=slot_accepted,
                    slot_available=not slot_accepted
                    and not adopted_existing_slot
                    and not (isinstance(exc, LockCodeUnverified) and exc.read_back_empty),
                )
            _record_lock_push_failure(
                door_code=door_code,
                error_message=error_message,
                terminal=False,
                lock_entity_id=lock_entity_id,
                counted=not _out_of_budget(zwavejs),
            )
            raise LockUnreachable("Lock did not accept the code in time; will retry.") from exc

        # Step 1: the PIN is confirmed, so claim the slot. Resetting the lock's
        # attempt counter is important: the cap is on *consecutive* failures, so
        # a single successful push must zero the meter. A code with a schedule
        # keeps the lock pending with schedule_pending until step 2 lands it, so
        # a schedule that fails (or a process that dies) after this still has the
        # slot on record and the scheduler sends only the schedule (issue #123).
        has_schedule = bool(door_code.days_of_week)
        # The PIN is in the slot now, so record it as an unconfirmed attempt first.
        # In autocommit (the only way a push runs, see _check_no_outer_transaction)
        # it commits on its own, so if the block below rolls back (the process dies,
        # a DB error, or the unique constraint) the slot isn't lost: a retry adopts
        # it and a delete or deactivate reads it back and clears it. It's tagged
        # slot_verified, since the readback above accepted the slot, so that holds
        # on a lock that masks PINs too. A clean commit deletes it again, so a
        # successful push leaves no failure in the audit log.
        pending_marker = _record_unconfirmed_slot_attempt(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            reason="PIN set on the lock, slot not saved yet",
            pin=pin,
            slot_verified=True,
        )
        before_stamp = _snapshot_push_fields(door_code)
        try:
            # One transaction for the slot, the lock's state, its event and the
            # code's rollup (issue #130), so a process that dies between them
            # can't leave the code pending with a slot nothing retries. A savepoint
            # inside an outer transaction, so a unique-constraint hit doesn't poison it.
            with transaction.atomic():
                pushed_at = django_timezone.now()
                # The code row before its assignment rows, the same order every
                # other writer of both takes, so two of them can't deadlock.
                _stamp_push_attempt(door_code=door_code, at=pushed_at)
                DoorCodeLockAssignment.objects.filter(door_code=door_code, lock_entity_id=lock_entity_id).update(
                    slot_index=slot_index,
                    push_state=DoorCode.PushState.PENDING if has_schedule else DoorCode.PushState.PUSHED,
                    push_attempt_count=0,
                    last_push_attempt_at=pushed_at,
                    last_push_error="",
                    schedule_pending=has_schedule,
                )
                DoorCodeEvent.objects.create(
                    door_code=door_code,
                    user=actor_user or door_code.user,
                    lock_entity_id=lock_entity_id,
                    event_type=DoorCodeEvent.EventType.CODE_SYNCED,
                    metadata={
                        "action": "pushed",
                        "slot_index": slot_index,
                        "schedule_applied": False,
                        **({"schedule_pending": True} if has_schedule else {}),
                        **({"adopted_existing_slot": True} if adopted_existing_slot else {}),
                        **({"resent_to_attempted_slot": True} if resend_to_attempted_slot else {}),
                    },
                )
                pending_marker.delete()
                refresh_push_state(door_code=door_code)
        except BaseException as exc:
            # The block rolled back, so the fields it set on door_code didn't
            # land either. Put them back to what they were before it, which a
            # failure recorded next then counts on top of (PR #195 review).
            _restore_push_fields(door_code, before_stamp)
            if not isinstance(exc, IntegrityError):
                raise
            # Another writer recorded this slot after we enumerated, so the lock
            # may now hold this PIN over that code's. Retrying would only park the
            # PIN in a second slot, so this lock fails terminally for the operator
            # to check. The code's other locks carry on (issue #126).
            raise _fail_slot_recorded_for_another_code(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index
            ) from exc

        weekdays_pushed: list[int] = []
        if has_schedule:
            weekdays_pushed = _push_schedule_to_slot(
                door_code=door_code,
                lock_entity_id=lock_entity_id,
                node_id=node_id,
                slot_index=slot_index,
                zwavejs=zwavejs,
                actor_user=actor_user,
                timeout_seconds=timeout_seconds,
                requeue_on_budget=True,
            )
        return _pushed_result(
            lock_entity_id=lock_entity_id, node_id=node_id, slot_index=slot_index, weekdays_pushed=weekdays_pushed
        )
    finally:
        _release_sync_lock(lock_key=lock_key, lock_id=lock_id)


_PUSH_FIELDS = ("push_state", "last_push_attempt_at", "last_push_error", "push_attempt_count", "updated_at")


def _snapshot_push_fields(door_code: DoorCode) -> dict[str, object]:
    return {name: getattr(door_code, name) for name in _PUSH_FIELDS}


def _restore_push_fields(door_code: DoorCode, snapshot: dict[str, object]) -> None:
    for name, value in snapshot.items():
        setattr(door_code, name, value)


def _pushed_result(*, lock_entity_id: str, node_id: int, slot_index: int, weekdays_pushed: list[int]) -> PushResult:
    """Tell the dispatcher the lock changed and build the push's result."""
    timestamp = django_timezone.now()
    try:
        from alarm.dispatcher import notify_entities_changed

        notify_entities_changed(
            source="lock_push",
            entity_ids=[lock_entity_id],
            changed_at=timestamp,
        )
    except Exception:
        logger.warning("Failed to notify dispatcher after push for %s", lock_entity_id, exc_info=True)

    return PushResult(
        lock_entity_id=lock_entity_id,
        node_id=node_id,
        slot_index=slot_index,
        schedule_applied=bool(weekdays_pushed),
        weekdays_pushed=weekdays_pushed,
        timestamp=timestamp,
    )


def _push_schedule_to_slot(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    node_id: int,
    slot_index: int,
    zwavejs: ZwavejsGateway,
    actor_user,
    timeout_seconds: float,
    requeue_on_budget: bool = False,
) -> list[int]:
    """Step 2 of a push: send the CC 78 schedule into the slot step 1 recorded, then mark the lock pushed (issue #123).

    The slot stays on record whatever happens, so a delete or deactivate still
    clears it. A transient failure leaves the lock ``pending`` with
    ``schedule_pending`` and one more attempt, and the scheduler sends only the
    schedule next time. A terminal one (a Z-Wave JS config error, or a window
    that ends before it starts) makes it ``failed`` with the slot kept and
    ``schedule_pending`` still set, so Retry sends only the schedule too.
    Success clears ``schedule_pending`` with a ``code_synced`` event
    (``action=schedule_pushed``). Returns the CC 78 weekdays pushed.

    With ``requeue_on_budget`` (the schedule right after the ``set``), a push
    that ran out of its time budget here queues the lock again when it has a
    live request (:data:`PUSH_REQUEST_TTL`), so the queued push task sends the
    schedule on its next tick instead of leaving the PIN working around the
    clock until the 300s retry (PR #201 review). A schedule-only push doesn't,
    so that's one more try at most.
    """
    try:
        weekdays_pushed = _push_daily_repeating_schedule(
            zwavejs=zwavejs,
            node_id=node_id,
            slot_index=slot_index,
            door_code=door_code,
            timeout_seconds=timeout_seconds,
        )
    except InvalidPin as exc:
        _record_lock_push_failure(
            door_code=door_code, lock_entity_id=lock_entity_id, error_message=str(exc), terminal=True
        )
        raise
    except (ZwavejsNotConfigured, ZwavejsClientUnavailable, ZwavejsCommandValidationError) as exc:
        _record_lock_push_failure(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            error_message=f"Schedule not applied: {exc}",
            terminal=True,
            event_metadata={"slot_index": int(slot_index), "schedule_pending": True},
        )
        raise LockPushFailed(str(exc)) from exc
    except GatewayError as exc:
        _record_lock_push_failure(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            error_message=f"Schedule not applied: {exc.__class__.__name__}: {exc}",
            terminal=False,
            counted=not _out_of_budget(zwavejs),
        )
        if requeue_on_budget and _out_of_budget(zwavejs):
            # Just after the attempt time the failure stamped, so the request isn't used up.
            DoorCodeLockAssignment.objects.filter(
                door_code=door_code,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                schedule_pending=True,
                push_state=DoorCode.PushState.PENDING,
                last_push_attempt_at__isnull=False,
                push_requested_at__gt=django_timezone.now() - PUSH_REQUEST_TTL,
            ).update(push_requested_at=F("last_push_attempt_at") + timedelta(microseconds=1))
        raise LockUnreachable("Lock did not accept the schedule in time; will retry.") from exc

    before_stamp = _snapshot_push_fields(door_code)
    try:
        with transaction.atomic():
            pushed_at = django_timezone.now()
            _stamp_push_attempt(door_code=door_code, at=pushed_at)
            DoorCodeLockAssignment.objects.filter(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index
            ).update(
                push_state=DoorCode.PushState.PUSHED,
                schedule_pending=False,
                push_attempt_count=0,
                last_push_attempt_at=pushed_at,
                last_push_error="",
            )
            DoorCodeEvent.objects.create(
                door_code=door_code,
                user=actor_user or door_code.user,
                lock_entity_id=lock_entity_id,
                event_type=DoorCodeEvent.EventType.CODE_SYNCED,
                metadata={
                    "action": "schedule_pushed",
                    "slot_index": int(slot_index),
                    "schedule_applied": bool(weekdays_pushed),
                    "weekdays": weekdays_pushed,
                },
            )
            refresh_push_state(door_code=door_code)
    except BaseException:
        _restore_push_fields(door_code, before_stamp)
        raise
    return weekdays_pushed


def _push_pending_schedule(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    node_id: int,
    slot_index: int,
    zwavejs: ZwavejsGateway,
    actor_user,
    timeout_seconds: float,
) -> PushResult:
    """Send only the schedule into a slot that already holds the PIN, no CC 99 ``set`` (issue #123).

    For a lock left ``schedule_pending`` by a schedule that didn't land (or a
    process that died) after its slot was recorded. The caller holds the lock
    and has read the code again. A window that ends before it starts is
    recorded as a terminal failure, the slot kept.
    """
    logger.info(
        "Re-sending only the schedule for door code id=%d to %s (node=%d slot=%d)",
        door_code.id,
        lock_entity_id,
        node_id,
        slot_index,
    )
    try:
        _validate_schedule_or_raise(door_code)
    except InvalidPin as exc:
        _record_lock_push_failure(
            door_code=door_code, lock_entity_id=lock_entity_id, error_message=str(exc), terminal=True
        )
        raise
    weekdays_pushed = _push_schedule_to_slot(
        door_code=door_code,
        lock_entity_id=lock_entity_id,
        node_id=node_id,
        slot_index=slot_index,
        zwavejs=zwavejs,
        actor_user=actor_user,
        timeout_seconds=timeout_seconds,
    )
    return _pushed_result(
        lock_entity_id=lock_entity_id, node_id=node_id, slot_index=slot_index, weekdays_pushed=weekdays_pushed
    )


def push_door_code_to_assigned_locks(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    actor_user=None,
    timeout_seconds: float = 5.0,
    only_unassigned: bool = True,
    include_failed: bool = False,
    lock_budget_seconds: float | None = None,
) -> tuple[list[PushResult], list[tuple[str, str]]]:
    """Push ``door_code`` to the locks it is assigned to, then refresh its rollup.

    ``lock_budget_seconds`` gives each lock's push its own :class:`BudgetedGateway`
    (the request path's inline fallback, issue #124).

    Returns ``(successes, failures)``. Failures is a list of ``(lock_entity_id, reason)``
    tuples; transient failures leave that lock ``pending`` for the scheduler.

    ``only_unassigned=True`` (the default) only pushes the locks that still need
    it: no slot yet, or a slot whose schedule is pending (issue #123). A lock
    whose push failed terminally is ``failed`` and skipped unless
    ``include_failed`` (Retry only), so one lock needing a human doesn't stop
    the scheduler retrying the others (issue #126). A lock the code is being
    dropped from is never pushed (issue #151).

    Each lock's outcome goes on its own assignment and
    :func:`refresh_push_state` works out the code's state from all of them, so
    one lock's success never hides another lock's failure.

    An inactive code is never pushed: it returns ``([], [])`` without touching the
    locks or the row (issue #138). Neither is one before its ``start_at`` or from
    its ``end_at`` on (issue #145). ``enforce_door_code_validity`` pushes it once
    it starts and retires it once it expires.
    """
    successes: list[PushResult] = []
    failures: list[tuple[str, str]] = []

    door_code.refresh_from_db(
        fields=["is_active", "push_state", "last_push_attempt_at", "last_push_error", *_VALIDITY_FIELDS]
    )
    if not door_code.is_active:
        logger.info("Not pushing inactive door code id=%s", door_code.id)
        return successes, failures
    if not belongs_on_lock(door_code):
        logger.info("Not pushing door code id=%s outside its start_at/end_at", door_code.id)
        return successes, failures
    # Sorted in Python so the prefetch is kept and the push order is deterministic.
    # It may be stale (the scheduler loaded it earlier), which is fine:
    # push_door_code_to_lock reads the lock's assignment again once it holds the
    # lock, so a lock an update already pushed or dropped isn't written twice (PR #157).
    assignments = sorted(door_code.lock_assignments.all(), key=lambda assignment: assignment.pk)
    for assignment in locks_to_push(
        door_code=door_code, assignments=assignments, include_failed=include_failed, only_unassigned=only_unassigned
    ):
        try:
            result = push_door_code_to_lock(
                door_code=door_code,
                lock_entity_id=assignment.lock_entity_id,
                zwavejs=zwavejs
                if lock_budget_seconds is None
                else BudgetedGateway(zwavejs, seconds=lock_budget_seconds),
                actor_user=actor_user,
                timeout_seconds=timeout_seconds,
            )
            successes.append(result)
        except PushSuperseded:
            # An update or delete got the lock first and settled the code's locks
            # and state itself, so this stale pass stops here.
            logger.info("Door code id=%s changed while its push waited for the lock; stopping", door_code.id)
            return successes, failures
        except (LockUnreachable, LockSlotsFull, LockPushFailed, InvalidPin) as exc:
            failures.append((assignment.lock_entity_id, str(exc)))

    refresh_push_state(door_code=door_code)
    return successes, failures


def push_or_settle_after_clear_retry(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    actor_user=None,
    include_failed: bool = False,
    lock_budget_seconds: float | None = None,
) -> tuple[list[PushResult], list[tuple[str, str]]]:
    """After :func:`retry_failed_slot_clears`, push an active code to the locks that need it.

    An inactive code is never pushed. Whatever it may still have on its locks
    with no clear failure on record (a tracked slot, or an unconfirmed attempt
    slot) is cleared first (:func:`clear_inactive_code_slots`, issue #158), and
    those still outstanding come back as the failures. It's ``pushed`` once
    nothing is left to clear, the same as a deactivate, since its locks then
    hold nothing. ``include_failed`` and ``lock_budget_seconds`` go to
    :func:`push_door_code_to_assigned_locks`.
    """
    door_code = DoorCode.objects.prefetch_related("lock_assignments").get(id=door_code.id)
    if not door_code.is_active:
        still_failing = clear_inactive_code_slots(door_code=door_code, zwavejs=zwavejs)
        failures = [(f.lock_entity_id, f.reason) for f in still_failing]
        # The clear may have waited behind an update that turned the code back on
        # (PR #167 review). That update owns its state now, so the rollup only
        # lands while the code is still off. A lock still busy, or a readback
        # that got no answer, leaves a slot behind with nothing recorded, so it
        # goes in the error.
        refresh_push_state(door_code=door_code, unrecorded_failures=still_failing, only_if_active=False)
        return [], failures
    successes, failures = push_door_code_to_assigned_locks(
        door_code=door_code,
        zwavejs=zwavejs,
        actor_user=actor_user,
        only_unassigned=True,
        include_failed=include_failed,
        lock_budget_seconds=lock_budget_seconds,
    )
    # Also for a code the push left alone (not started, expired), whose clears may have changed.
    refresh_push_state(door_code=door_code)
    return successes, failures


# The scheduler task that pushes what request_push queued, in locks/tasks.py (issue #124).
PUSH_REQUESTED_TASK = "push_requested_door_codes"

# How long a queued push stays queued. A lock still busy that long is left to
# push_pending_door_codes, which retries every pending lock every 300s anyway.
PUSH_REQUEST_TTL = timedelta(minutes=10)


def push_task_running() -> bool:
    """Whether this process runs :data:`PUSH_REQUESTED_TASK`, so a push :func:`request_push` queues goes out in seconds.

    It's the scheduler's own record of the task's loop
    (:func:`scheduler.runner.is_task_running`): a live thread that isn't
    stopping, which is also the only thing :func:`scheduler.runner.wake_task`
    reaches. So it's false with ``SCHEDULER_ENABLED=False``, in tests and
    management commands, and in a process that didn't get the leader lock, and
    the save pushes inline there like before (issue #124).
    """
    from scheduler.runner import is_task_running

    return is_task_running(PUSH_REQUESTED_TASK)


def _wake_push_task() -> None:
    from scheduler.runner import wake_task

    wake_task(PUSH_REQUESTED_TASK)


def request_push(
    code: DoorCode,
    lock_entity_ids: list[str] | None = None,
    *,
    actor_user=None,
) -> list[str]:
    """Queue a push of ``code`` to its locks for :data:`PUSH_REQUESTED_TASK` instead of pushing it now (issue #124).

    Stamps ``push_requested_at`` and ``push_requested_by`` (the actor on the
    ``code_synced`` event the push records) on the locks a push would send
    something to, by :func:`locks_to_push`'s rule, limited to
    ``lock_entity_ids`` when given. Nothing for a code that's inactive, not
    started or expired, since nothing pushes one of those. The code row is
    taken first like every writer of a code's assignments. The task is woken
    once the caller's transaction commits, never on a rollback, and a wake in a
    process that doesn't run the task does nothing (the stamp still is
    picked up by the process that does, within its 5s tick). Returns the locks
    stamped.
    """
    now = django_timezone.now()
    wanted = None if lock_entity_ids is None else set(lock_entity_ids)
    with transaction.atomic():
        row = _lock_code_row(code.id)
        if row is None or not row.is_active or not belongs_on_lock(row, now=now):
            return []
        locks = [a for a in locks_to_push(door_code=row) if wanted is None or a.lock_entity_id in wanted]
        if not locks:
            return []
        DoorCodeLockAssignment.objects.filter(id__in=[a.id for a in locks]).update(
            push_requested_at=now, push_requested_by=actor_user
        )
        transaction.on_commit(_wake_push_task, robust=True)
    return sorted(a.lock_entity_id for a in locks)


def queued_push_assignments(*, now: datetime, max_attempts: int):
    """The locks :data:`PUSH_REQUESTED_TASK` pushes at ``now``, as a ``DoorCodeLockAssignment`` queryset (issue #124).

    ``pending`` and needing a ``set`` or a schedule, not being dropped, under
    the cap, on a code that's active, started and not expired, and with a
    ``push_requested_at`` inside :data:`PUSH_REQUEST_TTL` that no push attempt
    on that lock has come after. Any attempt counts, the scheduler's 300s retry
    and an inline push included, so a request is used up by the first push that
    gets to the lock. :func:`locks_to_push` has the rest of the rule (a slot
    with a clear outstanding), which needs the code's events.
    """
    pushable = DoorCode.objects.filter(is_active=True).filter(started_q(now) & ~expired_q(now))
    queued = (
        DoorCodeLockAssignment.objects.filter(
            door_code__in=pushable,
            push_state=DoorCode.PushState.PENDING,
            push_requested_at__gt=now - PUSH_REQUEST_TTL,
        )
        .filter(Q(slot_index__isnull=True) | Q(schedule_pending=True))
        .filter(Q(last_push_attempt_at__isnull=True) | Q(last_push_attempt_at__lt=F("push_requested_at")))
        .exclude(being_removed_q())
    )
    if max_attempts > 0:
        queued = queued.filter(push_attempt_count__lt=max_attempts)
    return queued

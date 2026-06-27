"""Z-Wave JS CC API call contracts.

Records the expected ``args`` shape for the Z-Wave JS Command Class API methods
Latchpoint invokes. The real ZJS server runs strict TypeScript runtime
validation on incoming calls — calls that don't match the expected positional
arg shape are rejected with messages like:

    Cannot determine type name for error {"kind":"parameter",
     "name":"userIdStatus","type":"literal","expected":"1",
     "actual":"string \"13795\""}

That exact error bit Latchpoint on prod (a 2-arg ``set`` call where the server
wanted 3 args). The unit-test FakeGateway records args without enforcing a
schema, so the mismatch shipped through CI.

This module captures the shape we tested against the real server. Tests run
:func:`validate_cc_api_args` against every recorded call so a future change
that drops, adds, or reorders a positional arg fails CI instead of prod.
"""

from __future__ import annotations

from typing import Any, Callable

# A typing rule for one positional arg: (human-readable type name, predicate).
ArgRule = tuple[str, Callable[[Any], bool]]


def _is_int(value: Any) -> bool:
    # bool is a subclass of int in Python; exclude it so True/False aren't
    # accepted as a slot/status integer.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


_T_INT: ArgRule = ("int", _is_int)
_T_STR: ArgRule = ("str", _is_str)
_T_DICT: ArgRule = ("dict", _is_dict)


# (command_class, method_name) -> tuple of (arg_name, ArgRule).
# Add an entry when a new CC API call ships in lock_push / lock_config_sync /
# anywhere else; tests for the call path will then enforce the shape.
CC_API_CONTRACTS: dict[tuple[int, str], tuple[tuple[str, ArgRule], ...]] = {
    # CC 99 (User Code) — UserCodeCCAPI.set(userId, userIdStatus, userCode).
    # userIdStatus = 1 means "Occupied" (the slot holds an active code).
    (99, "set"): (
        ("userId", _T_INT),
        ("userIdStatus", _T_INT),
        ("userCode", _T_STR),
    ),
    # CC 99 (User Code) — UserCodeCCAPI.clear(userId).
    (99, "clear"): (("userId", _T_INT),),
    # CC 78 (Schedule Entry Lock) — setDailyRepeatingSchedule(slot, schedule).
    # slot = {userId, slotId}; schedule = {weekdays[], startHour, startMinute,
    # durationHour, durationMinute}. Two positional args — the ZJS server spreads
    # them and validates the inner fields.
    (78, "setDailyRepeatingSchedule"): (("slot", _T_DICT), ("schedule", _T_DICT)),
}


class CcApiContractViolation(AssertionError):
    """The args passed to invoke_cc_api don't match the known CC contract."""


def validate_cc_api_args(*, command_class: int, method_name: str, args: list | None) -> None:
    """Raise :class:`CcApiContractViolation` if ``args`` doesn't match the contract.

    Unknown ``(command_class, method_name)`` combos pass through unvalidated —
    only entries explicitly listed in :data:`CC_API_CONTRACTS` are enforced.
    """
    contract = CC_API_CONTRACTS.get((command_class, method_name))
    if contract is None:
        return
    actual_args = list(args or [])
    if len(actual_args) != len(contract):
        expected_names = ", ".join(name for name, _ in contract)
        raise CcApiContractViolation(
            f"CC {command_class} {method_name}: expected {len(contract)} args "
            f"({expected_names}); got {len(actual_args)} ({actual_args!r})"
        )
    for index, ((name, (type_name, predicate)), value) in enumerate(zip(contract, actual_args, strict=True)):
        if not predicate(value):
            raise CcApiContractViolation(
                f"CC {command_class} {method_name}: arg {index} ({name}) "
                f"expected {type_name}, got {type(value).__name__}={value!r}"
            )

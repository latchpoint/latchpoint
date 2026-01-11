from __future__ import annotations

import math
import re
from typing import Any

from django.utils import timezone
from zoneinfo import ZoneInfo


def _nearest_rank_percentile(scores: list[float], *, p: int) -> float | None:
    """Return the nearest-rank percentile value (1..100) from a list of numeric scores."""
    if not scores:
        return None
    if not isinstance(p, int) or p <= 0 or p > 100:
        return None
    ordered = sorted(scores)
    n = len(ordered)
    k = int(math.ceil((p / 100.0) * n))  # 1-based rank
    k = max(1, min(n, k))
    return float(ordered[k - 1])


def _is_mapping(value: Any) -> bool:
    """Return True when `value` is a dict (used for loose JSON schema checks)."""
    return isinstance(value, dict)


def _get_op(node: Any) -> str | None:
    """Extract the `op` string from a condition node."""
    if not _is_mapping(node):
        return None
    op = node.get("op")
    return op if isinstance(op, str) else None


def extract_for(node: Any) -> tuple[int | None, Any]:
    """Extract `for` operator seconds and child node, returning (seconds, child)."""
    if _get_op(node) != "for":
        return None, node
    if not _is_mapping(node):
        return None, node
    seconds = node.get("seconds")
    child = node.get("child")
    if not isinstance(seconds, int) or seconds <= 0:
        return None, child
    return seconds, child


_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM_RE = re.compile(r"^(?P<hour>\d{2}):(?P<minute>\d{2})$")


def _parse_hhmm(value: Any) -> int | None:
    """Parse 'HH:MM' into minutes since midnight."""
    if not isinstance(value, str):
        return None
    m = _HHMM_RE.match(value.strip())
    if not m:
        return None
    hour = int(m.group("hour"))
    minute = int(m.group("minute"))
    if hour < 0 or hour > 23:
        return None
    if minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _normalize_days(value: Any) -> tuple[list[str] | None, list[str] | None]:
    """Return (normalized_days, errors)."""
    if value is None:
        return list(_DAYS), None
    if not isinstance(value, list):
        return None, ["must be a list of day strings (mon..sun)"]
    normalized: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            return None, ["must be a list of day strings (mon..sun)"]
        day = raw.strip().lower()
        if day not in _DAYS:
            return None, [f"invalid day: {raw}"]
        if day not in normalized:
            normalized.append(day)
    if not normalized:
        return None, ["must include at least one day"]
    return normalized, None


def _resolve_tzinfo(value: Any) -> tuple[timezone.tzinfo | None, list[str] | None]:
    """Return (tzinfo, errors)."""
    if value is None or value == "":
        return timezone.get_current_timezone(), None
    if not isinstance(value, str):
        return None, ["must be 'system' or an IANA time zone id"]
    tz = value.strip()
    if tz == "system":
        return timezone.get_current_timezone(), None
    try:
        return ZoneInfo(tz), None
    except Exception:
        return None, ["invalid time zone id"]


def _when_has_triggerable_condition(node: Any) -> bool:
    """Return True if the condition tree has at least one non-time trigger operator."""
    if not isinstance(node, dict):
        return False
    op = node.get("op")
    if op in {"entity_state", "alarm_state_in", "frigate_person_detected"}:
        return True
    if op in {"time_in_range"}:
        return False
    if op in {"all", "any"}:
        children = node.get("children", [])
        return isinstance(children, list) and any(_when_has_triggerable_condition(c) for c in children)
    if op in {"not", "for"}:
        return _when_has_triggerable_condition(node.get("child"))
    return False


def _when_has_time_in_range(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    op = node.get("op")
    if op == "time_in_range":
        return True
    if op in {"all", "any"}:
        children = node.get("children", [])
        return isinstance(children, list) and any(_when_has_time_in_range(c) for c in children)
    if op in {"not", "for"}:
        return _when_has_time_in_range(node.get("child"))
    return False


def validate_when_node(node: Any) -> dict[str, Any] | None:
    """
    Validate a WHEN condition tree.

    Returns an errors dict suitable for DRF serializers, or None when valid/empty.
    """
    return _validate_when_node(node, is_root=True)


def _validate_when_node(node: Any, *, is_root: bool) -> dict[str, Any] | None:
    if node is None or node == {}:
        return None
    if not isinstance(node, dict):
        return {"non_field_errors": ["must be an object"]}

    op = node.get("op")
    if not isinstance(op, str) or not op.strip():
        return {"op": ["missing op"]}

    errors: dict[str, Any] = {}

    if op in {"all", "any"}:
        children = node.get("children")
        if not isinstance(children, list) or not children:
            errors["children"] = ["must be a non-empty list"]
        else:
            child_errors: dict[int, Any] = {}
            for idx, child in enumerate(children):
                e = _validate_when_node(child, is_root=False)
                if e:
                    child_errors[idx] = e
            if child_errors:
                errors["children"] = child_errors

    elif op == "not":
        child = node.get("child")
        e = _validate_when_node(child, is_root=False)
        if e:
            errors["child"] = e

    elif op == "for":
        seconds = node.get("seconds")
        if not isinstance(seconds, int) or seconds <= 0:
            errors["seconds"] = ["must be a positive integer"]
        child = node.get("child")
        e = _validate_when_node(child, is_root=False)
        if e:
            errors["child"] = e

    elif op == "entity_state":
        entity_id = node.get("entity_id")
        equals = node.get("equals")
        if not isinstance(entity_id, str) or not entity_id.strip():
            errors["entity_id"] = ["required"]
        if not isinstance(equals, str) or not equals.strip():
            errors["equals"] = ["required"]

    elif op == "alarm_state_in":
        states_raw = node.get("states")
        if not isinstance(states_raw, list) or not states_raw:
            errors["states"] = ["must be a non-empty list"]
        else:
            states = [str(s).strip() for s in states_raw if isinstance(s, str) and str(s).strip()]
            if not states:
                errors["states"] = ["must contain valid state strings"]

    elif op == "frigate_person_detected":
        cameras = node.get("cameras")
        within_seconds = node.get("within_seconds")
        min_confidence_pct = node.get("min_confidence_pct")
        if not isinstance(cameras, list) or not [c for c in cameras if isinstance(c, str) and c.strip()]:
            errors["cameras"] = ["must be a non-empty list of camera strings"]
        if not isinstance(within_seconds, int) or within_seconds <= 0:
            errors["within_seconds"] = ["must be a positive integer"]
        try:
            threshold = float(min_confidence_pct)
            if threshold < 0 or threshold > 100:
                errors["min_confidence_pct"] = ["must be between 0 and 100"]
        except Exception:
            errors["min_confidence_pct"] = ["must be a number between 0 and 100"]

    elif op == "time_in_range":
        start_raw = node.get("start")
        end_raw = node.get("end")
        start_min = _parse_hhmm(start_raw)
        end_min = _parse_hhmm(end_raw)
        if start_min is None:
            errors["start"] = ["must be HH:MM (24-hour)"]
        if end_min is None:
            errors["end"] = ["must be HH:MM (24-hour)"]
        if start_min is not None and end_min is not None and start_min == end_min:
            errors["end"] = ["must not equal start"]

        days_norm, days_errors = _normalize_days(node.get("days"))
        if days_errors:
            errors["days"] = days_errors

        _, tz_errors = _resolve_tzinfo(node.get("tz"))
        if tz_errors:
            errors["tz"] = tz_errors

    else:
        errors["op"] = [f"unsupported op: {op}"]

    # Guardrail: time-only rules won't fire without a time-based dispatcher.
    if (
        is_root
        and not errors
        and _when_has_time_in_range(node)
        and not _when_has_triggerable_condition(node)
    ):
        errors["non_field_errors"] = [
            "time_in_range must be combined with at least one entity/alarm/frigate condition"
        ]

    return errors or None


def eval_condition(node: Any, *, entity_state: dict[str, str | None]) -> bool:
    """Evaluate a condition node using only an entity-state map (no repository context)."""
    return eval_condition_with_context(node, entity_state=entity_state, now=None, repos=None)


def eval_condition_with_context(
    node: Any,
    *,
    entity_state: dict[str, str | None],
    now=None,
    repos: Any = None,
) -> bool:
    """Evaluate a condition node, optionally using repositories for alarm/frigate context."""
    op = _get_op(node)
    if not op:
        return False

    if op == "all":
        if not _is_mapping(node):
            return False
        children = node.get("children")
        if not isinstance(children, list) or not children:
            return False
        return all(eval_condition_with_context(child, entity_state=entity_state, now=now, repos=repos) for child in children)

    if op == "any":
        if not _is_mapping(node):
            return False
        children = node.get("children")
        if not isinstance(children, list) or not children:
            return False
        return any(eval_condition_with_context(child, entity_state=entity_state, now=now, repos=repos) for child in children)

    if op == "not":
        if not _is_mapping(node):
            return False
        return not eval_condition_with_context(node.get("child"), entity_state=entity_state, now=now, repos=repos)

    if op == "entity_state":
        if not _is_mapping(node):
            return False
        entity_id = node.get("entity_id")
        equals = node.get("equals")
        if not isinstance(entity_id, str) or not isinstance(equals, str):
            return False
        current = entity_state.get(entity_id)
        return current == equals

    if op == "alarm_state_in":
        if not _is_mapping(node):
            return False
        states_raw = node.get("states")
        if not isinstance(states_raw, list) or not states_raw:
            return False
        states = [str(s).strip() for s in states_raw if isinstance(s, str) and str(s).strip()]
        if not states:
            return False
        current_state = None
        try:
            if repos is not None and hasattr(repos, "get_alarm_state"):
                current_state = repos.get_alarm_state()
        except Exception:
            current_state = None
        return isinstance(current_state, str) and current_state in set(states)

    if op == "frigate_person_detected":
        if not _is_mapping(node):
            return False

        cameras_raw = node.get("cameras")
        zones_raw = node.get("zones")
        within_seconds = node.get("within_seconds")
        min_confidence_pct = node.get("min_confidence_pct")
        aggregation = node.get("aggregation") or "max"
        percentile = node.get("percentile")
        on_unavailable = node.get("on_unavailable") or "treat_as_no_match"

        if not isinstance(cameras_raw, list) or not cameras_raw:
            return False
        cameras = [str(c).strip() for c in cameras_raw if isinstance(c, str) and str(c).strip()]
        if not cameras:
            return False

        zones: list[str] = []
        if isinstance(zones_raw, list) and zones_raw:
            zones = [str(z).strip() for z in zones_raw if isinstance(z, str) and str(z).strip()]

        if not isinstance(within_seconds, int) or within_seconds <= 0:
            return False
        try:
            threshold = float(min_confidence_pct)
        except Exception:
            return False
        if threshold < 0 or threshold > 100:
            return False

        now_dt = now or timezone.now()
        since = now_dt - timezone.timedelta(seconds=int(within_seconds))

        candidates: list[Any] = []
        try:
            if repos is not None and hasattr(repos, "list_frigate_detections"):
                candidates = repos.list_frigate_detections("person", cameras, since)
        except Exception:
            candidates = []

        if zones:
            want = set(zones)
            candidates = [c for c in candidates if want.intersection(set(getattr(c, "zones", []) or []))]

        scores: list[float] = []
        for c in candidates:
            try:
                scores.append(float(getattr(c, "confidence_pct")))
            except Exception:
                continue

        if scores:
            if aggregation == "latest":
                latest = max(candidates, key=lambda c: getattr(c, "observed_at", now_dt))
                try:
                    value = float(getattr(latest, "confidence_pct"))
                except Exception:
                    value = None
            elif aggregation == "percentile":
                if not isinstance(percentile, int):
                    return False
                value = _nearest_rank_percentile(scores, p=percentile)
            else:  # "max" default
                value = max(scores) if scores else None

            return (value is not None) and (value >= threshold)

        # No candidates: decide based on availability policy.
        available = False
        try:
            if repos is not None and hasattr(repos, "frigate_is_available"):
                available = bool(repos.frigate_is_available(now_dt))
        except Exception:
            available = False

        if not available and on_unavailable == "treat_as_match":
            return True
        return False

    if op == "time_in_range":
        if not _is_mapping(node):
            return False
        start_min = _parse_hhmm(node.get("start"))
        end_min = _parse_hhmm(node.get("end"))
        if start_min is None or end_min is None:
            return False
        if start_min == end_min:
            return False

        days, days_errors = _normalize_days(node.get("days"))
        if days_errors or not days:
            return False

        tzinfo, tz_errors = _resolve_tzinfo(node.get("tz"))
        if tz_errors or tzinfo is None:
            return False

        now_dt = now or timezone.now()
        if timezone.is_naive(now_dt):
            now_dt = timezone.make_aware(now_dt)
        local_dt = timezone.localtime(now_dt, tzinfo)
        weekday = _DAYS[local_dt.weekday()]
        if weekday not in set(days):
            return False

        current_min = local_dt.hour * 60 + local_dt.minute
        if end_min > start_min:
            return (current_min >= start_min) and (current_min < end_min)
        # Wrap across midnight (e.g. 22:00–06:00)
        return (current_min >= start_min) or (current_min < end_min)

    return False


def eval_condition_explain(node: Any, *, entity_state: dict[str, str | None]) -> tuple[bool, dict[str, Any]]:
    """Evaluate and return (ok, trace) using only an entity-state map (no repository context)."""
    return eval_condition_explain_with_context(node, entity_state=entity_state, now=None, repos=None)


def eval_condition_explain_with_context(
    node: Any,
    *,
    entity_state: dict[str, str | None],
    now=None,
    repos: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """Evaluate and return (ok, trace), including diagnostics for repository-backed operators."""
    op = _get_op(node)
    if not op:
        return False, {"op": None, "ok": False, "reason": "missing_op"}

    if op in {"all", "any"}:
        if not _is_mapping(node):
            return False, {"op": op, "ok": False, "reason": "invalid_node"}
        children = node.get("children")
        if not isinstance(children, list) or not children:
            return False, {"op": op, "ok": False, "reason": "missing_children"}
        explained: list[dict[str, Any]] = []
        if op == "all":
            ok_all = True
            for child in children:
                ok_child, trace = eval_condition_explain_with_context(child, entity_state=entity_state, now=now, repos=repos)
                explained.append(trace)
                if not ok_child:
                    ok_all = False
            return ok_all, {"op": "all", "ok": ok_all, "children": explained}
        ok_any = False
        for child in children:
            ok_child, trace = eval_condition_explain_with_context(child, entity_state=entity_state, now=now, repos=repos)
            explained.append(trace)
            if ok_child:
                ok_any = True
        return ok_any, {"op": "any", "ok": ok_any, "children": explained}

    if op == "not":
        if not _is_mapping(node):
            return False, {"op": "not", "ok": False, "reason": "invalid_node"}
        ok_child, trace = eval_condition_explain_with_context(node.get("child"), entity_state=entity_state, now=now, repos=repos)
        return (not ok_child), {"op": "not", "ok": (not ok_child), "child": trace}

    if op == "time_in_range":
        if not _is_mapping(node):
            return False, {"op": "time_in_range", "ok": False, "reason": "invalid_node"}

        start_raw = node.get("start")
        end_raw = node.get("end")
        start_min = _parse_hhmm(start_raw)
        end_min = _parse_hhmm(end_raw)
        if start_min is None or end_min is None or start_min == end_min:
            return False, {
                "op": "time_in_range",
                "ok": False,
                "reason": "invalid_start_end",
                "start": start_raw,
                "end": end_raw,
            }

        days, days_errors = _normalize_days(node.get("days"))
        tzinfo, tz_errors = _resolve_tzinfo(node.get("tz"))
        if days_errors or tz_errors or not days or tzinfo is None:
            return False, {
                "op": "time_in_range",
                "ok": False,
                "reason": "invalid_days_or_tz",
                "days_errors": days_errors,
                "tz_errors": tz_errors,
            }

        now_dt = now or timezone.now()
        if timezone.is_naive(now_dt):
            now_dt = timezone.make_aware(now_dt)
        local_dt = timezone.localtime(now_dt, tzinfo)
        weekday = _DAYS[local_dt.weekday()]
        current_min = local_dt.hour * 60 + local_dt.minute

        if weekday not in set(days):
            return False, {
                "op": "time_in_range",
                "ok": False,
                "reason": "day_not_allowed",
                "weekday": weekday,
                "days": days,
            }

        if end_min > start_min:
            ok = (current_min >= start_min) and (current_min < end_min)
        else:
            ok = (current_min >= start_min) or (current_min < end_min)

        return ok, {
            "op": "time_in_range",
            "ok": ok,
            "start": start_raw,
            "end": end_raw,
            "weekday": weekday,
            "tz": node.get("tz") or "system",
        }

    if op == "entity_state":
        if not _is_mapping(node):
            return False, {"op": "entity_state", "ok": False, "reason": "invalid_node"}
        entity_id = node.get("entity_id")
        equals = node.get("equals")
        if not isinstance(entity_id, str) or not isinstance(equals, str):
            return False, {"op": "entity_state", "ok": False, "reason": "missing_fields"}
        current = entity_state.get(entity_id)
        ok = current == equals
        return ok, {
            "op": "entity_state",
            "ok": ok,
            "entity_id": entity_id,
            "expected": equals,
            "actual": current,
        }

    if op == "alarm_state_in":
        if not _is_mapping(node):
            return False, {"op": "alarm_state_in", "ok": False, "reason": "invalid_node"}
        states_raw = node.get("states")
        if not isinstance(states_raw, list) or not states_raw:
            return False, {"op": "alarm_state_in", "ok": False, "reason": "missing_states"}
        states = [str(s).strip() for s in states_raw if isinstance(s, str) and str(s).strip()]
        if not states:
            return False, {"op": "alarm_state_in", "ok": False, "reason": "missing_states"}
        current_state = None
        repo_error = None
        try:
            if repos is not None and hasattr(repos, "get_alarm_state"):
                current_state = repos.get_alarm_state()
        except Exception as exc:
            repo_error = str(exc)
        ok = isinstance(current_state, str) and current_state in set(states)
        return ok, {
            "op": "alarm_state_in",
            "ok": ok,
            "states": states,
            "current_state": current_state,
            "error": repo_error,
        }

    if op == "frigate_person_detected":
        if not _is_mapping(node):
            return False, {"op": "frigate_person_detected", "ok": False, "reason": "invalid_node"}

        cameras_raw = node.get("cameras")
        zones_raw = node.get("zones")
        within_seconds = node.get("within_seconds")
        min_confidence_pct = node.get("min_confidence_pct")
        aggregation = node.get("aggregation") or "max"
        percentile = node.get("percentile")
        on_unavailable = node.get("on_unavailable") or "treat_as_no_match"

        if not isinstance(cameras_raw, list) or not cameras_raw:
            return False, {"op": "frigate_person_detected", "ok": False, "reason": "missing_cameras"}
        cameras = [str(c).strip() for c in cameras_raw if isinstance(c, str) and str(c).strip()]
        if not cameras:
            return False, {"op": "frigate_person_detected", "ok": False, "reason": "missing_cameras"}

        zones: list[str] = []
        if isinstance(zones_raw, list) and zones_raw:
            zones = [str(z).strip() for z in zones_raw if isinstance(z, str) and str(z).strip()]

        if not isinstance(within_seconds, int) or within_seconds <= 0:
            return False, {"op": "frigate_person_detected", "ok": False, "reason": "invalid_within_seconds"}
        try:
            threshold = float(min_confidence_pct)
        except Exception:
            return False, {"op": "frigate_person_detected", "ok": False, "reason": "invalid_threshold"}
        if threshold < 0 or threshold > 100:
            return False, {"op": "frigate_person_detected", "ok": False, "reason": "invalid_threshold"}

        now_dt = now or timezone.now()
        since = now_dt - timezone.timedelta(seconds=int(within_seconds))

        candidates: list[Any] = []
        repo_error: str | None = None
        try:
            if repos is not None and hasattr(repos, "list_frigate_detections"):
                candidates = repos.list_frigate_detections("person", cameras, since)
        except Exception as exc:
            repo_error = str(exc)
            candidates = []

        if zones:
            want = set(zones)
            candidates = [c for c in candidates if want.intersection(set(getattr(c, "zones", []) or []))]

        scores: list[float] = []
        for c in candidates:
            try:
                scores.append(float(getattr(c, "confidence_pct")))
            except Exception:
                continue

        value: float | None = None
        if scores:
            if aggregation == "latest":
                latest = max(candidates, key=lambda c: getattr(c, "observed_at", now_dt))
                try:
                    value = float(getattr(latest, "confidence_pct"))
                except Exception:
                    value = None
            elif aggregation == "percentile":
                if not isinstance(percentile, int):
                    return False, {"op": "frigate_person_detected", "ok": False, "reason": "invalid_percentile"}
                value = _nearest_rank_percentile(scores, p=percentile)
            else:
                value = max(scores) if scores else None

            ok = (value is not None) and (value >= threshold)
            return ok, {
                "op": "frigate_person_detected",
                "ok": ok,
                "label": "person",
                "cameras": cameras,
                "zones": zones,
                "within_seconds": within_seconds,
                "aggregation": aggregation,
                "percentile": percentile if aggregation == "percentile" else None,
                "min_confidence_pct": threshold,
                "candidates_count": len(scores),
                "value_pct": value,
            }

        available = False
        try:
            if repos is not None and hasattr(repos, "frigate_is_available"):
                available = bool(repos.frigate_is_available(now_dt))
        except Exception as exc:
            repo_error = repo_error or str(exc)
            available = False

        ok = bool((not available) and (on_unavailable == "treat_as_match"))
        return ok, {
            "op": "frigate_person_detected",
            "ok": ok,
            "label": "person",
            "cameras": cameras,
            "zones": zones,
            "within_seconds": within_seconds,
            "aggregation": aggregation,
            "percentile": percentile if aggregation == "percentile" else None,
            "min_confidence_pct": threshold,
            "candidates_count": 0,
            "value_pct": None,
            "available": available,
            "on_unavailable": on_unavailable,
            "reason": "unavailable_treated_as_match" if ok else ("unavailable" if not available else "no_candidates"),
            "error": repo_error,
        }

    return False, {"op": op, "ok": False, "reason": "unsupported_op"}

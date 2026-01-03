from __future__ import annotations

import math
from typing import Any

from django.utils import timezone


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

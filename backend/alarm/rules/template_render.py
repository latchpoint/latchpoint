"""Template variable rendering for rule notification messages (ADR-0088).

Renders ``{{trigger.entity_id}}``-style placeholders in rule action message
fields against the entity that satisfied the rule's ``when``. Unknown roots,
missing path segments, and underscore-prefixed segments render as the literal
``{{...}}`` text. Rendering is single-pass: a substituted value is not
re-scanned for further ``{{...}}`` tokens within the same call. The renderer
never raises.

The allow-list of root keys (``trigger``, ``triggers``, ``rule``, ``now``)
must stay in sync with ``frontend/src/features/rules/templateVariables.ts``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.utils import timezone

from alarm.models import Entity, Rule

_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")
_ALLOWED_ROOTS = frozenset({"trigger", "triggers", "rule", "now"})

_MISSING: Any = object()


@dataclass(frozen=True)
class TriggerContext:
    """Triggering-entity context made available to action handlers."""

    fired_at: datetime
    fire_source: str = "timer"
    trigger: Entity | None = None
    triggers: list[Entity] = field(default_factory=list)

    @classmethod
    def empty(cls, fired_at: datetime | None = None, *, fire_source: str = "timer") -> TriggerContext:
        """Build an empty TriggerContext for callers without entity context."""
        return cls(fired_at=fired_at or timezone.now(), fire_source=fire_source)


def render(template: str | None, *, rule: Rule, triggers: TriggerContext) -> str:
    """Render ``{{var.path}}`` placeholders. Unknown paths pass through literally."""
    if not template or "{{" not in template:
        return template or ""

    ctx = _build_context(rule=rule, triggers=triggers)

    def _sub(match: re.Match[str]) -> str:
        path = match.group(1)
        segments = path.split(".")
        if any(seg.startswith("_") for seg in segments):
            return match.group(0)
        root = segments[0]
        if root not in _ALLOWED_ROOTS:
            return match.group(0)
        value = _resolve(ctx[root], segments[1:])
        if value is _MISSING:
            return match.group(0)
        return str(value)

    return _PATTERN.sub(_sub, template)


def _build_context(*, rule: Rule, triggers: TriggerContext) -> dict[str, Any]:
    """Assemble the per-render context dict keyed by allow-listed root."""
    return {
        "trigger": _Trigger(triggers.trigger),
        "triggers": _Triggers(triggers.triggers),
        "rule": _Rule(rule),
        "now": _Now(triggers.fired_at),
    }


def _resolve(node: Any, segments: list[str]) -> Any:
    """Walk ``segments`` against ``node``; return ``_MISSING`` on any failure."""
    if not segments:
        # Bare root (e.g. ``{{triggers}}``).
        return node.bare() if hasattr(node, "bare") else _MISSING
    cursor: Any = node
    for seg in segments:
        if seg.startswith("_"):
            return _MISSING
        nxt = _step(cursor, seg)
        if nxt is _MISSING:
            return _MISSING
        cursor = nxt
    return cursor


def _step(cursor: Any, segment: str) -> Any:
    """Take one resolution step; return ``_MISSING`` if the segment isn't allowed."""
    if cursor is None:
        return _MISSING
    if isinstance(cursor, dict):
        return cursor.get(segment, _MISSING)
    if hasattr(cursor, "_get"):
        return cursor._get(segment)
    return _MISSING


class _Trigger:
    """Resolution wrapper for ``{{trigger.*}}`` paths."""

    __slots__ = ("_entity",)

    def __init__(self, entity: Entity | None) -> None:
        """Capture the (possibly absent) trigger entity."""
        self._entity = entity

    def bare(self) -> Any:
        """Resolve a bare ``{{trigger}}`` token to the entity's friendly name."""
        return self._entity.name if self._entity is not None else _MISSING

    def _get(self, name: str) -> Any:
        """Resolve one path segment under ``trigger``."""
        ent = self._entity
        if ent is None:
            return _MISSING
        if name == "entity_id":
            return ent.entity_id
        if name == "name":
            return ent.name
        if name == "state":
            return ent.last_state if ent.last_state is not None else ""
        if name == "source":
            return ent.source or ""
        if name == "domain":
            return ent.domain
        if name == "attributes":
            attrs = ent.attributes if isinstance(ent.attributes, dict) else {}
            return _AttrDict(attrs)
        return _MISSING


class _Triggers:
    """Resolution wrapper for ``{{triggers}}`` (bare only in v1)."""

    __slots__ = ("_entities",)

    def __init__(self, entities: list[Entity]) -> None:
        """Capture the matched-entity list."""
        self._entities = entities

    def bare(self) -> str:
        """Resolve a bare ``{{triggers}}`` token to a comma-joined name list."""
        return ", ".join(e.name for e in self._entities)

    def _get(self, _name: str) -> Any:
        """``{{triggers.<x>}}`` is not supported in v1."""
        return _MISSING


class _Rule:
    """Resolution wrapper for ``{{rule.*}}`` paths."""

    __slots__ = ("_rule",)

    def __init__(self, rule: Rule) -> None:
        """Capture the firing rule."""
        self._rule = rule

    def bare(self) -> Any:
        """Resolve a bare ``{{rule}}`` token to the rule's name.

        Mirrors ``{{trigger}}`` (friendly name) and ``{{now}}`` (formatted time)
        — the bare form of a root key resolves to its most useful single value.
        """
        return self._rule.name

    def _get(self, name: str) -> Any:
        """Resolve one path segment under ``rule``."""
        if name == "name":
            return self._rule.name
        if name == "kind":
            return self._rule.kind
        return _MISSING


class _Now:
    """Resolution wrapper for ``{{now}}`` and ``{{now.iso}}``."""

    __slots__ = ("_dt",)

    def __init__(self, dt: datetime) -> None:
        """Capture the fired-at timestamp."""
        self._dt = dt

    def bare(self) -> str:
        """Resolve a bare ``{{now}}`` to a human-readable local-time string."""
        return timezone.localtime(self._dt).strftime("%Y-%m-%d %H:%M:%S")

    def _get(self, name: str) -> Any:
        """Resolve ``{{now.iso}}``; other paths fall through to literal."""
        if name == "iso":
            return self._dt.isoformat()
        return _MISSING


class _AttrDict:
    """Resolution wrapper for ``{{trigger.attributes.<key>}}`` paths."""

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        """Capture the entity's attributes dict."""
        self._data = data

    def _get(self, name: str) -> Any:
        """Look up one key, str-coercing scalars; return ``_MISSING`` if absent."""
        if name in self._data:
            value = self._data[name]
            if value is None:
                return _MISSING
            if isinstance(value, dict):
                return _AttrDict(value)
            return value
        return _MISSING

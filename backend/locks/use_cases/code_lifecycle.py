"""When a door code is valid, from its own fields (issue #145).

The PIN only belongs on a lock from ``start_at`` up to ``end_at``. ``end_at`` is
exclusive, so a code is expired at ``end_at`` itself. These only look at the
dates (and the use count), never at ``code_type`` or ``source``, since lock syncs
before #166 turned temporary manual codes into permanent synced ones that kept
their dates. Callers compare against one ``now`` per pass so every check in it agrees.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from django.db.models import Q
from django.utils import timezone as django_timezone

from locks.models import DoorCode

Validity = Literal["scheduled", "valid", "expired", "exhausted"]


def _now(now: datetime | None) -> datetime:
    return now if now is not None else django_timezone.now()


def starts_by(start_at: datetime | None, *, now: datetime | None = None) -> bool:
    """Whether a code with this ``start_at`` has started at ``now``. No ``start_at`` means it always has."""
    return start_at is None or start_at <= _now(now)


def ended_by(end_at: datetime | None, *, now: datetime | None = None) -> bool:
    """Whether a code with this ``end_at`` has expired at ``now``. ``end_at`` itself is expired."""
    return end_at is not None and end_at <= _now(now)


def is_started(code: DoorCode, *, now: datetime | None = None) -> bool:
    """Whether ``code``'s ``start_at`` has passed (or it has none)."""
    return starts_by(code.start_at, now=now)


def is_expired(code: DoorCode, *, now: datetime | None = None) -> bool:
    """Whether ``code``'s ``end_at`` has been reached."""
    return ended_by(code.end_at, now=now)


def is_exhausted(code: DoorCode) -> bool:
    """Whether ``code`` has used up its uses: ``max_uses`` when set, one for a one-time code.

    Nothing counts door code uses yet, so this stays false until that lands.
    """
    limit = code.max_uses
    if limit is None and code.code_type == DoorCode.CodeType.ONE_TIME:
        limit = 1
    return limit is not None and (code.uses_count or 0) >= limit


def validity(code: DoorCode, *, now: datetime | None = None) -> Validity:
    """``expired``, ``exhausted``, ``scheduled`` (not started yet) or ``valid``, in that order."""
    now = _now(now)
    if is_expired(code, now=now):
        return "expired"
    if is_exhausted(code):
        return "exhausted"
    if not is_started(code, now=now):
        return "scheduled"
    return "valid"


def belongs_on_lock(code: DoorCode, *, now: datetime | None = None) -> bool:
    """Whether ``code``'s dates allow its PIN on a lock at ``now``: started and not expired."""
    now = _now(now)
    return is_started(code, now=now) and not is_expired(code, now=now)


def started_q(now: datetime) -> Q:
    """:func:`is_started` as a ``DoorCode`` filter."""
    return Q(start_at__isnull=True) | Q(start_at__lte=now)


def expired_q(now: datetime) -> Q:
    """:func:`is_expired` as a ``DoorCode`` filter."""
    return Q(end_at__isnull=False, end_at__lte=now)

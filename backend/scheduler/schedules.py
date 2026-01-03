"""Schedule type definitions for the task scheduler."""

from __future__ import annotations

from dataclasses import dataclass


class Schedule:
    """Base class for schedules."""

    pass


@dataclass
class DailyAt(Schedule):
    """Run once daily at specified time (uses Django TIME_ZONE setting)."""

    hour: int = 3
    minute: int = 0


@dataclass
class Every(Schedule):
    """Run at fixed intervals."""

    seconds: int = 3600  # Default: hourly
    jitter: int = 0  # Optional random jitter in seconds to avoid thundering herd

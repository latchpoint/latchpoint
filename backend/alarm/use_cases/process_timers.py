from __future__ import annotations

from dataclasses import dataclass

from alarm import services


@dataclass(frozen=True)
class TimerTickResult:
    state: str

    def as_dict(self) -> dict[str, str]:
        """Serialize timer tick result to a JSON-friendly dict."""
        return {"alarm_state": self.state}


def tick_alarm_timers() -> TimerTickResult:
    """Advance due timers in the alarm state machine and return the resulting state."""
    snapshot = services.timer_expired()
    return TimerTickResult(state=snapshot.current_state)

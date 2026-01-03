from __future__ import annotations

from dataclasses import dataclass

from alarm.models import AlarmSettingsProfile, AlarmStateSnapshot
from alarm.state_machine.settings import get_setting_int, get_setting_json


@dataclass(frozen=True)
class TimingSnapshot:
    delay_time: int
    arming_time: int
    trigger_time: int

    def as_dict(self) -> dict[str, int]:
        """Serialize timing to a JSON-friendly dict."""
        return {
            "delay_time": self.delay_time,
            "arming_time": self.arming_time,
            "trigger_time": self.trigger_time,
        }


def base_timing(profile: AlarmSettingsProfile) -> TimingSnapshot:
    """Return base timing values from the settings profile."""
    return TimingSnapshot(
        delay_time=get_setting_int(profile, "delay_time"),
        arming_time=get_setting_int(profile, "arming_time"),
        trigger_time=get_setting_int(profile, "trigger_time"),
    )


def resolve_timing(profile: AlarmSettingsProfile, target_state: str) -> TimingSnapshot:
    """Resolve timing for a target state, applying per-state overrides when present."""
    timing = base_timing(profile)
    overrides = get_setting_json(profile, "state_overrides") or {}
    if isinstance(overrides, dict):
        override = overrides.get(target_state) or {}
        if isinstance(override, dict):
            timing = TimingSnapshot(
                delay_time=override.get("delay_time", timing.delay_time),
                arming_time=override.get("arming_time", timing.arming_time),
                trigger_time=override.get("trigger_time", timing.trigger_time),
            )
    return timing


def timing_from_snapshot(snapshot: AlarmStateSnapshot) -> TimingSnapshot:
    """Resolve timing from a snapshot's stored timing_snapshot, falling back to base profile timing."""
    timing = base_timing(snapshot.settings_profile)
    if snapshot.timing_snapshot:
        timing = TimingSnapshot(
            delay_time=snapshot.timing_snapshot.get("delay_time", timing.delay_time),
            arming_time=snapshot.timing_snapshot.get("arming_time", timing.arming_time),
            trigger_time=snapshot.timing_snapshot.get("trigger_time", timing.trigger_time),
        )
    return timing

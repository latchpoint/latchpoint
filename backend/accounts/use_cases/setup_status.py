from __future__ import annotations

from accounts.models import User, UserCode
from alarm.models import AlarmSettingsProfile, AlarmStateSnapshot, Sensor
from alarm.state_machine.transitions import get_current_snapshot
from alarm.use_cases.settings_profile import ensure_active_settings_profile


def compute_setup_status(*, user: User) -> dict:
    """Compute and return setup status flags used by the frontend to gate setup flow."""
    # Historically the app had a multi-step setup wizard. We now bootstrap
    # required defaults lazily so setup can happen from the Settings page.
    ensure_active_settings_profile()
    get_current_snapshot(process_timers=False)

    has_active_settings_profile = AlarmSettingsProfile.objects.filter(is_active=True).exists()
    has_alarm_snapshot = AlarmStateSnapshot.objects.exists()
    has_alarm_code = UserCode.objects.filter(user=user, is_active=True).exists()
    has_sensors = Sensor.objects.exists()
    home_assistant_connected = False

    setup_required = False

    return {
        "onboarding_required": False,
        "setup_required": setup_required,
        "requirements": {
            "has_active_settings_profile": has_active_settings_profile,
            "has_alarm_snapshot": has_alarm_snapshot,
            "has_alarm_code": has_alarm_code,
            "has_sensors": has_sensors,
            "home_assistant_connected": home_assistant_connected,
        },
    }

from __future__ import annotations

from alarm.models import AlarmState

ARMED_STATES = {
    AlarmState.ARMED_HOME,
    AlarmState.ARMED_AWAY,
    AlarmState.ARMED_NIGHT,
    AlarmState.ARMED_VACATION,
}


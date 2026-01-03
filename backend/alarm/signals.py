from __future__ import annotations

from django.dispatch import Signal

# Sent after an alarm state transition is committed.
# Args: state_to (str)
alarm_state_change_committed = Signal()

# Sent after settings profile entries or active profile change is committed.
# Args: profile_id (int), reason (str)
settings_profile_changed = Signal()

# Sent when an integration transitions online/offline.
# Args: integration (str), is_healthy (bool), previous_healthy (bool | None)
integration_status_changed = Signal()

# Sent on each status tick (even if status didn't change).
# Args: integration (str), is_healthy (bool), checked_at (datetime)
integration_status_observed = Signal()

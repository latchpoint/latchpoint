from __future__ import annotations

from django.db import models


class HomeAssistantMqttAlarmEntityStatus(models.Model):
    """
    Persisted status for Home Assistant alarm entity publishing over MQTT discovery.

    This intentionally stores only timestamps and error summaries (no secrets).
    """

    profile = models.OneToOneField(
        "alarm.AlarmSettingsProfile",
        on_delete=models.CASCADE,
        related_name="home_assistant_mqtt_alarm_entity_status",
    )
    last_discovery_publish_at = models.DateTimeField(null=True, blank=True)
    last_state_publish_at = models.DateTimeField(null=True, blank=True)
    last_availability_publish_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "alarm_homeassistantmqttalarmentitystatus"

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.profile_id}:home_assistant_mqtt_alarm_entity_status"

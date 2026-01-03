from __future__ import annotations

from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator


class ControlPanelIntegrationType(models.TextChoices):
    ZWAVEJS = "zwavejs", "Z-Wave JS"
    HOME_ASSISTANT = "home_assistant", "Home Assistant"


class ControlPanelKind(models.TextChoices):
    RING_KEYPAD_V2 = "ring_keypad_v2", "Ring Keypad v2"


class ControlPanelAction(models.TextChoices):
    DISARM = "disarm", "Disarm"
    ARM_HOME = "arm_home", "Arm home"
    ARM_AWAY = "arm_away", "Arm away"
    CANCEL = "cancel", "Cancel"


class ControlPanelDevice(models.Model):
    """
    A physical control panel device (e.g. Ring Keypad v2).

    `external_key` is an integration-specific unique identifier, e.g.:
    - zwavejs:{home_id}:{node_id}
    - home_assistant:{device_id}
    """

    name = models.CharField(max_length=150)
    integration_type = models.CharField(max_length=32, choices=ControlPanelIntegrationType.choices)
    kind = models.CharField(max_length=64, choices=ControlPanelKind.choices)
    enabled = models.BooleanField(default=True)

    external_key = models.CharField(max_length=200, unique=True)
    external_id = models.JSONField(default=dict, blank=True)

    # App-driven beep/indicator volume used by the "test" endpoint and other device sound actions.
    # Ring Keypad v2 Indicator CC volume is a 1-99 value.
    beep_volume = models.PositiveSmallIntegerField(
        default=50,
        validators=[MinValueValidator(1), MaxValueValidator(99)],
    )

    # Per-device mapping from a panel action (e.g. "arm_home") to an alarm state (e.g. "armed_home")
    # or a special transition key (e.g. "cancel_arming").
    action_map = models.JSONField(default=dict, blank=True)

    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["integration_type"]),
            models.Index(fields=["kind"]),
            models.Index(fields=["enabled"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        """Return a human-friendly identifier for logs/admin lists."""
        return self.name

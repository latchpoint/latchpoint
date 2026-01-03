from __future__ import annotations

from django.db import models
from django.db.models import Q


class FrigateDetection(models.Model):
    """
    Normalized detection record ingested from Frigate MQTT events.

    Stored for deterministic rules evaluation (no network calls during rule evaluation).
    """

    provider = models.CharField(max_length=32, default="frigate", db_index=True)
    event_id = models.CharField(max_length=128, blank=True, db_index=True)
    label = models.CharField(max_length=64, db_index=True)
    camera = models.CharField(max_length=128, db_index=True)
    zones = models.JSONField(default=list, blank=True)
    confidence_pct = models.FloatField()
    observed_at = models.DateTimeField(db_index=True)
    source_topic = models.CharField(max_length=255, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["provider", "label", "-observed_at"]),
            models.Index(fields=["provider", "camera", "-observed_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"],
                condition=~Q(event_id=""),
                name="frigate_detection_provider_event_id_unique_nonempty",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover
        """Return a compact representation for logs/admin lists."""
        return f"{self.provider}:{self.label}:{self.camera}:{self.observed_at.isoformat()}"

import uuid

from django.db import models
from django.utils import timezone

from alarm.models import AlarmSettingsProfile


class NotificationProvider(models.Model):
    """A configured notification provider instance."""

    class ProviderType(models.TextChoices):
        PUSHBULLET = "pushbullet", "Pushbullet"
        DISCORD = "discord", "Discord"
        TELEGRAM = "telegram", "Telegram"
        PUSHOVER = "pushover", "Pushover"
        NTFY = "ntfy", "Ntfy"
        EMAIL = "email", "Email (SMTP)"
        TWILIO_SMS = "twilio_sms", "Twilio SMS"
        TWILIO_CALL = "twilio_call", "Twilio Voice Call"
        SLACK = "slack", "Slack"
        WEBHOOK = "webhook", "Webhook"
        HOME_ASSISTANT = "home_assistant", "Home Assistant"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        AlarmSettingsProfile,
        on_delete=models.CASCADE,
        related_name="notification_providers",
    )
    name = models.CharField(max_length=100, help_text="Display name for this provider")
    provider_type = models.CharField(
        max_length=50,
        choices=ProviderType.choices,
        help_text="Type of notification provider",
    )
    config = models.JSONField(
        default=dict,
        help_text="Provider configuration (sensitive fields are encrypted)",
    )
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["profile", "name"]
        ordering = ["name"]
        verbose_name = "Notification Provider"
        verbose_name_plural = "Notification Providers"

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"


class NotificationLog(models.Model):
    """Audit log for sent notifications."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        NotificationProvider,
        on_delete=models.SET_NULL,
        null=True,
        related_name="logs",
    )
    # Denormalized fields for history (provider may be deleted)
    provider_name = models.CharField(max_length=100)
    provider_type = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=Status.choices)
    message_preview = models.CharField(
        max_length=200,
        help_text="Truncated message for audit purposes",
    )
    error_message = models.TextField(blank=True)
    error_code = models.CharField(max_length=50, blank=True)
    rule_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Name of rule that triggered this notification",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification Log"
        verbose_name_plural = "Notification Logs"

    def __str__(self):
        return f"{self.provider_name} - {self.status} - {self.created_at}"


class NotificationDelivery(models.Model):
    """Durable outbox record for notification delivery attempts."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        DEAD = "dead", "Dead"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        AlarmSettingsProfile,
        on_delete=models.CASCADE,
        related_name="notification_deliveries",
    )
    provider = models.ForeignKey(
        NotificationProvider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )
    provider_key = models.CharField(
        max_length=64,
        help_text="UUID of provider or system provider id (e.g. ha-system-provider)",
    )
    message = models.TextField()
    title = models.CharField(max_length=200, blank=True)
    data = models.JSONField(default=dict, blank=True)
    rule_name = models.CharField(max_length=200, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)

    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=50, blank=True)
    last_error_message = models.TextField(blank=True)

    idempotency_key = models.CharField(
        max_length=64,
        unique=True,
        help_text="Optional unique key to deduplicate enqueue attempts",
        default=uuid.uuid4,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider_key} - {self.status} - {self.created_at}"

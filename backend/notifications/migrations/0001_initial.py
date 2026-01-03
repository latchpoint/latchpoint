# Generated manually for NotificationProvider and NotificationLog models

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("alarm", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationProvider",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text="Display name for this provider",
                        max_length=100,
                    ),
                ),
                (
                    "provider_type",
                    models.CharField(
                        choices=[
                            ("pushbullet", "Pushbullet"),
                            ("discord", "Discord"),
                            ("telegram", "Telegram"),
                            ("pushover", "Pushover"),
                            ("ntfy", "Ntfy"),
                            ("email", "Email (SMTP)"),
                            ("twilio_sms", "Twilio SMS"),
                            ("twilio_call", "Twilio Voice Call"),
                            ("slack", "Slack"),
                            ("webhook", "Webhook"),
                            ("home_assistant", "Home Assistant"),
                        ],
                        help_text="Type of notification provider",
                        max_length=50,
                    ),
                ),
                (
                    "config",
                    models.JSONField(
                        default=dict,
                        help_text="Provider configuration (sensitive fields are encrypted)",
                    ),
                ),
                ("is_enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_providers",
                        to="alarm.alarmsettingsprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Notification Provider",
                "verbose_name_plural": "Notification Providers",
                "ordering": ["name"],
                "unique_together": {("profile", "name")},
            },
        ),
        migrations.CreateModel(
            name="NotificationLog",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("provider_name", models.CharField(max_length=100)),
                ("provider_type", models.CharField(max_length=50)),
                (
                    "status",
                    models.CharField(
                        choices=[("success", "Success"), ("failed", "Failed")],
                        max_length=20,
                    ),
                ),
                (
                    "message_preview",
                    models.CharField(
                        help_text="Truncated message for audit purposes",
                        max_length=200,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                ("error_code", models.CharField(blank=True, max_length=50)),
                (
                    "rule_name",
                    models.CharField(
                        blank=True,
                        help_text="Name of rule that triggered this notification",
                        max_length=200,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "provider",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="logs",
                        to="notifications.notificationprovider",
                    ),
                ),
            ],
            options={
                "verbose_name": "Notification Log",
                "verbose_name_plural": "Notification Logs",
                "ordering": ["-created_at"],
            },
        ),
    ]

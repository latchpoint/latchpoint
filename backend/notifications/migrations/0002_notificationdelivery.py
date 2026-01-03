# Generated manually for NotificationDelivery model

import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ("alarm", "0001_initial"),
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationDelivery",
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
                    "provider_key",
                    models.CharField(
                        help_text="UUID of provider or system provider id (e.g. ha-system-provider)",
                        max_length=64,
                    ),
                ),
                ("message", models.TextField()),
                ("title", models.CharField(blank=True, max_length=200)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("rule_name", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sending", "Sending"),
                            ("sent", "Sent"),
                            ("dead", "Dead"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("max_attempts", models.PositiveIntegerField(default=5)),
                (
                    "next_attempt_at",
                    models.DateTimeField(db_index=True, default=timezone.now),
                ),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, max_length=50)),
                ("last_error_message", models.TextField(blank=True)),
                (
                    "idempotency_key",
                    models.CharField(
                        default=uuid.uuid4,
                        help_text="Optional unique key to deduplicate enqueue attempts",
                        max_length=64,
                        unique=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_deliveries",
                        to="alarm.alarmsettingsprofile",
                    ),
                ),
                (
                    "provider",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="deliveries",
                        to="notifications.notificationprovider",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="notificationdelivery",
            index=models.Index(fields=["status", "next_attempt_at"], name="notificatio_status_3cbf75_idx"),
        ),
    ]

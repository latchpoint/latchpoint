from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("alarm", "0007_seed_state_overrides_exit_delays"),
    ]

    operations = [
        migrations.CreateModel(
            name="MqttIntegrationStatus",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_discovery_publish_at", models.DateTimeField(blank=True, null=True)),
                ("last_state_publish_at", models.DateTimeField(blank=True, null=True)),
                ("last_availability_publish_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mqtt_status",
                        to="alarm.alarmsettingsprofile",
                    ),
                ),
            ],
        ),
    ]


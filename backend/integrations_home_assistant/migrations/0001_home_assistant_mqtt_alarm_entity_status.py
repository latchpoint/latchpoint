from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("alarm", "0009_rename_mqtt_integration_status"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="HomeAssistantMqttAlarmEntityStatus",
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
                                related_name="home_assistant_mqtt_alarm_entity_status",
                                to="alarm.alarmsettingsprofile",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "alarm_homeassistantmqttalarmentitystatus",
                    },
                ),
            ],
        ),
    ]


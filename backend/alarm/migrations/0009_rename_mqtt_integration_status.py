from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("alarm", "0008_mqtt_integration_status"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="MqttIntegrationStatus",
            new_name="HomeAssistantMqttAlarmEntityStatus",
        ),
    ]


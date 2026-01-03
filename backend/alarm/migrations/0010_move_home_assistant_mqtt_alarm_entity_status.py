from __future__ import annotations

from django.db import migrations


def _migrate_content_type(apps, schema_editor) -> None:
    ContentType = apps.get_model("contenttypes", "ContentType")
    ContentType.objects.filter(
        app_label="alarm",
        model="homeassistantmqttalarmentitystatus",
    ).update(app_label="integrations_home_assistant")


class Migration(migrations.Migration):
    dependencies = [
        ("integrations_home_assistant", "0001_home_assistant_mqtt_alarm_entity_status"),
        ("alarm", "0009_rename_mqtt_integration_status"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(_migrate_content_type, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.DeleteModel(name="HomeAssistantMqttAlarmEntityStatus"),
            ],
        ),
    ]


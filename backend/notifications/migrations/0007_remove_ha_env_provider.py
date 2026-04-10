"""Remove orphaned 'Home Assistant (env)' notification providers.

The HA system provider (ha-system-provider) already handles Home Assistant
notifications; the env-provisioned DB row was redundant and has been removed
from the provider registry.
"""

from django.db import migrations


def remove_ha_env_providers(apps, schema_editor):
    NotificationProvider = apps.get_model("notifications", "NotificationProvider")
    NotificationProvider.objects.filter(name="Home Assistant (env)").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0006_alter_notificationprovider_config"),
    ]

    operations = [
        migrations.RunPython(remove_ha_env_providers, migrations.RunPython.noop),
    ]

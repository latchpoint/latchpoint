"""
Check the integration settings on boot. `docker/entrypoint.sh` runs this after `migrate`, before daphne.

It used to apply them as well: connect MQTT and Z-Wave JS, publish the HA MQTT alarm entity discovery and
subscribe for Zigbee2MQTT and Frigate. All of that lived in this process, which exits before daphne starts,
so none of it carried over to the server, and daphne connected again a few seconds later. The server
applies the settings itself from `AppConfig.ready()` and the MQTT on-connect hooks, so this only reads
them now and opens no connections (#164).

Reading them still makes sure the active profile and its settings entries exist, and decrypting the MQTT and
Z-Wave JS settings fails the boot here if SETTINGS_ENCRYPTION_KEY can't read them. The server's `ready()`
swallows that error and would start without its connections.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from alarm.state_machine.settings import get_active_settings_profile, get_setting_json


def _enabled(raw: object) -> bool:
    return isinstance(raw, dict) and bool(raw.get("enabled"))


class Command(BaseCommand):
    help = (
        "Check the integration settings (MQTT, Z-Wave JS, HA MQTT alarm entity, Zigbee2MQTT, Frigate) on boot. "
        "Opens no connections, the server process applies them when it starts."
    )

    def handle(self, *args, **options):
        """Read the integration settings and report what the server will apply."""
        from integrations_zwavejs.views import get_zwavejs_settings
        from transports_mqtt.views import get_mqtt_settings

        mqtt_settings = get_mqtt_settings()
        zwavejs_settings = get_zwavejs_settings()
        profile = get_active_settings_profile()

        self._report("MQTT", _enabled(mqtt_settings), "the server connects when it starts")
        self._report("Z-Wave JS", _enabled(zwavejs_settings), "the server connects when it starts")
        self._report(
            "Home Assistant MQTT alarm entity",
            _enabled(get_setting_json(profile, "home_assistant_alarm_entity")),
            "the server publishes discovery once MQTT connects",
        )
        self._report(
            "Zigbee2MQTT",
            _enabled(get_setting_json(profile, "zigbee2mqtt")),
            "the server subscribes once MQTT connects",
        )
        self._report(
            "Frigate",
            _enabled(get_setting_json(profile, "frigate")),
            "the server subscribes once MQTT connects",
        )

    def _report(self, name: str, enabled: bool, when_enabled: str) -> None:
        if enabled:
            self.stdout.write(f"{name} is enabled, {when_enabled}.")
        else:
            self.stdout.write(f"{name} is disabled.")

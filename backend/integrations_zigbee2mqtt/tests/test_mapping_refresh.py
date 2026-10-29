"""The device mapping refresh runs from the on-connect hook, and only when Zigbee2MQTT is enabled (#164)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations_zigbee2mqtt import runtime


class _FakeMqttManager:
    def __init__(self) -> None:
        self.hooks: list = []

    def register_on_connect(self, callback) -> None:
        self.hooks.append(callback)


class InitializeMappingRefreshTests(SimpleTestCase):
    def _initialize(self, *, enabled: bool) -> tuple[_FakeMqttManager, object]:
        fake = _FakeMqttManager()
        patches = (
            patch.object(runtime, "_initialized", False),
            patch.object(runtime, "mqtt_connection_manager", fake),
            patch.object(runtime, "get_settings", return_value=SimpleNamespace(enabled=enabled)),
            patch.object(runtime, "_mqtt_enabled", return_value=True),
            patch.object(runtime, "_subscribe_for_ingest"),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        refresh_patch = patch.object(runtime, "refresh_device_mapping_async")
        refresh = refresh_patch.start()
        self.addCleanup(refresh_patch.stop)

        runtime.initialize()
        return fake, refresh

    def test_doesnt_refresh_before_mqtt_connects(self):
        # The server's startup runs before MQTT connects, where a refresh can only fail to publish and log a
        # traceback. The hook refreshes once it connects (or right away, if it already has).
        fake, refresh = self._initialize(enabled=True)

        refresh.assert_not_called()
        self.assertEqual(len(fake.hooks), 1)

    def test_the_hook_refreshes_when_enabled(self):
        fake, refresh = self._initialize(enabled=True)

        fake.hooks[0]()

        refresh.assert_called_once()

    def test_the_hook_skips_when_disabled(self):
        fake, refresh = self._initialize(enabled=False)

        fake.hooks[0]()

        refresh.assert_not_called()

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

import scheduler.telemetry as telemetry_module


class GetInstanceIdTests(SimpleTestCase):
    """`get_instance_id()` must return the stable default with no override,
    and honor SCHEDULER_INSTANCE_ID when set. See ADR-0093."""

    def setUp(self) -> None:
        self._original_cache = telemetry_module._CACHED_INSTANCE_ID
        telemetry_module._CACHED_INSTANCE_ID = None

    def tearDown(self) -> None:
        telemetry_module._CACHED_INSTANCE_ID = self._original_cache

    @override_settings(SCHEDULER_INSTANCE_ID=None)
    def test_returns_default_when_no_override(self) -> None:
        self.assertEqual(telemetry_module.get_instance_id(), "default")

    @override_settings(SCHEDULER_INSTANCE_ID="")
    def test_returns_default_when_override_is_blank(self) -> None:
        self.assertEqual(telemetry_module.get_instance_id(), "default")

    @override_settings(SCHEDULER_INSTANCE_ID="replica-2")
    def test_uses_override_when_set(self) -> None:
        self.assertEqual(telemetry_module.get_instance_id(), "replica-2")

    @override_settings(SCHEDULER_INSTANCE_ID="  trimmed  ")
    def test_strips_override_whitespace(self) -> None:
        self.assertEqual(telemetry_module.get_instance_id(), "trimmed")

    @override_settings(SCHEDULER_INSTANCE_ID="cached-value")
    def test_result_is_cached(self) -> None:
        first = telemetry_module.get_instance_id()
        with override_settings(SCHEDULER_INSTANCE_ID="something-else"):
            second = telemetry_module.get_instance_id()
        self.assertEqual(first, second)

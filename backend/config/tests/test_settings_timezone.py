from __future__ import annotations

import importlib
import os

from django.test import SimpleTestCase

from config import settings as settings_module


class TimeZoneEnvVarTests(SimpleTestCase):
    """Lock in that Django's TIME_ZONE sources from the TZ env var (ADR-0090).

    Reloads `config.settings` with TZ set so the module-load-time
    `env.str("TZ", ...)` read is exercised against a known value. A refactor
    that flipped the env-var name back to TIME_ZONE would trip this guard.
    """

    def setUp(self):
        self._prev_tz = os.environ.get("TZ")

    def tearDown(self):
        if self._prev_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._prev_tz
        importlib.reload(settings_module)

    def test_tz_env_var_drives_django_time_zone(self):
        os.environ["TZ"] = "America/Chicago"
        importlib.reload(settings_module)
        self.assertEqual(settings_module.TIME_ZONE, "America/Chicago")

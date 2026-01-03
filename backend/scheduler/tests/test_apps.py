from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from scheduler.apps import _should_start


class ShouldStartTests(SimpleTestCase):
    @override_settings(SCHEDULER_ENABLED=True, IS_TESTING=False)
    def test_starts_under_daphne_with_flags(self):
        with patch("scheduler.apps.sys.argv", ["/usr/bin/daphne", "-b", "0.0.0.0", "config.asgi:application"]):
            self.assertTrue(_should_start())

    @override_settings(SCHEDULER_ENABLED=True, IS_TESTING=False)
    def test_does_not_start_for_migrate(self):
        with patch("scheduler.apps.sys.argv", ["manage.py", "migrate"]):
            self.assertFalse(_should_start())


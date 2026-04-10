from __future__ import annotations

import os
from unittest.mock import patch

from django.test import TestCase

from alarm.models import AlarmSettingsProfile
from notifications.models import NotificationProvider
from notifications.provider_registry import ensure_env_providers_exist


class EnsureEnvProvidersExistTest(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.filter(is_active=True).first()
        if self.profile is None:
            self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def _count(self, provider_type: str) -> int:
        return NotificationProvider.objects.filter(profile=self.profile, provider_type=provider_type).count()

    def test_creates_provider_when_configured_and_no_row_exists(self):
        with patch.dict(os.environ, {"PUSHBULLET_ACCESS_TOKEN": "o.abc123"}):
            ensure_env_providers_exist(self.profile)

        self.assertEqual(self._count("pushbullet"), 1)
        provider = NotificationProvider.objects.get(profile=self.profile, provider_type="pushbullet")
        # New providers are created disabled by default (ADR 0078)
        self.assertFalse(provider.is_enabled)
        self.assertEqual(provider.config, {})

    def test_no_op_when_already_exists(self):
        existing = NotificationProvider.objects.create(
            profile=self.profile,
            name="Pushbullet (env)",
            provider_type="pushbullet",
            config={},
            is_enabled=False,
        )
        original_updated_at = existing.updated_at

        with patch.dict(os.environ, {"PUSHBULLET_ACCESS_TOKEN": "o.abc123"}):
            ensure_env_providers_exist(self.profile)

        existing.refresh_from_db()
        # Existing rows are never modified
        self.assertEqual(existing.updated_at, original_updated_at)

    def test_no_op_when_not_configured(self):
        # No env vars set — handler.is_configured_from_env() returns False
        ensure_env_providers_exist(self.profile)

        self.assertEqual(self._count("pushbullet"), 0)

    def test_multiple_providers_processed(self):
        with patch.dict(
            os.environ,
            {
                "PUSHBULLET_ACCESS_TOKEN": "o.abc123",
                "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
            },
        ):
            ensure_env_providers_exist(self.profile)

        providers = NotificationProvider.objects.filter(profile=self.profile)
        self.assertEqual(providers.count(), 2)
        types = set(providers.values_list("provider_type", flat=True))
        self.assertEqual(types, {"pushbullet", "discord"})

    def test_corrects_provider_type_mismatch(self):
        """If an existing row has the wrong provider_type, it gets corrected."""
        existing = NotificationProvider.objects.create(
            profile=self.profile,
            name="Pushbullet (env)",
            provider_type="discord",  # wrong type for this name
            config={},
            is_enabled=True,
        )

        with patch.dict(os.environ, {"PUSHBULLET_ACCESS_TOKEN": "o.abc123"}):
            ensure_env_providers_exist(self.profile)

        existing.refresh_from_db()
        self.assertEqual(existing.provider_type, "pushbullet")
        self.assertTrue(existing.is_enabled)

    def test_handler_without_is_configured_from_env_skipped(self):
        """A provider type whose handler lacks is_configured_from_env is silently skipped."""

        class _MinimalHandler:
            display_name = "Stub"

        with (
            patch("notifications.provider_registry._PROVIDER_TYPES", ["stub_type"]),
            patch("notifications.handlers.get_handler", return_value=_MinimalHandler()),
        ):
            ensure_env_providers_exist(self.profile)  # must not raise

        self.assertEqual(
            NotificationProvider.objects.filter(profile=self.profile, provider_type="stub_type").count(),
            0,
        )

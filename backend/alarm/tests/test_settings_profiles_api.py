from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmSettingsProfile


class AlarmSettingsProfilesApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="admin@example.com", password="pass", is_staff=True)
        self.user = User.objects.create_user(email="user@example.com", password="pass")

    def test_get_active_settings_bootstraps(self):
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.get(reverse("alarm-settings"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(AlarmSettingsProfile.objects.filter(is_active=True).exists())

    def test_profiles_list(self):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(reverse("alarm-settings-profiles"))
        self.assertEqual(response.status_code, 200)

    def test_profiles_create_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.user)

        response = client.post(reverse("alarm-settings-profiles"), data={"name": "New Profile"})
        self.assertEqual(response.status_code, 403)

    def test_profiles_crud_and_activate(self):
        client = APIClient()
        client.force_authenticate(self.admin)

        created = client.post(
            reverse("alarm-settings-profiles"),
            data={"name": "Quick Response"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        profile_id = created.data["id"]

        updated = client.patch(
            reverse("alarm-settings-profile-detail", kwargs={"profile_id": profile_id}),
            data={"entries": [{"key": "delay_time", "value": 31}]},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        entry_by_key = {row["key"]: row for row in updated.data["entries"]}
        self.assertEqual(entry_by_key["delay_time"]["value"], 31)

        activated = client.post(reverse("alarm-settings-profile-activate", kwargs={"profile_id": profile_id}))
        self.assertEqual(activated.status_code, 200)
        self.assertTrue(AlarmSettingsProfile.objects.get(id=profile_id).is_active)

        blocked_delete = client.delete(reverse("alarm-settings-profile-detail", kwargs={"profile_id": profile_id}))
        self.assertEqual(blocked_delete.status_code, 400)

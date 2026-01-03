from __future__ import annotations

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmEvent, AlarmEventType


class AlarmEventsApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="events@example.com", password="pass")
        self.other_user = User.objects.create_user(email="other@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_list_events_paginates(self):
        now = timezone.now()
        for i in range(0, 25):
            AlarmEvent.objects.create(
                event_type=AlarmEventType.STATE_CHANGED,
                timestamp=now - timezone.timedelta(minutes=i),
            )

        response = self.client.get(reverse("events"), data={"page_size": 20})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["data"]), 20)
        self.assertEqual(body["meta"]["total"], 25)
        self.assertTrue(body["meta"]["has_next"])

    def test_list_events_filters(self):
        now = timezone.now()
        armed = AlarmEvent.objects.create(
            event_type=AlarmEventType.ARMED,
            timestamp=now - timezone.timedelta(minutes=10),
            user=self.user,
        )
        AlarmEvent.objects.create(
            event_type=AlarmEventType.DISARMED,
            timestamp=now - timezone.timedelta(minutes=5),
            user=self.user,
        )
        AlarmEvent.objects.create(
            event_type=AlarmEventType.ARMED,
            timestamp=now - timezone.timedelta(minutes=1),
            user=self.other_user,
        )

        response = self.client.get(
            reverse("events"),
            data={"event_type": AlarmEventType.ARMED, "user_id": str(self.user.id)},
        )
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.json()["data"]]
        self.assertEqual(ids, [armed.id])

    def test_list_events_filters_date_range(self):
        now = timezone.now()
        before_window = AlarmEvent.objects.create(
            event_type=AlarmEventType.STATE_CHANGED,
            timestamp=now - timezone.timedelta(days=2),
        )
        inside_window = AlarmEvent.objects.create(
            event_type=AlarmEventType.STATE_CHANGED,
            timestamp=now - timezone.timedelta(hours=2),
        )
        after_window = AlarmEvent.objects.create(
            event_type=AlarmEventType.STATE_CHANGED,
            timestamp=now - timezone.timedelta(minutes=10),
        )

        response = self.client.get(
            reverse("events"),
            data={
                "start_date": (now - timezone.timedelta(hours=3)).isoformat(),
                "end_date": (now - timezone.timedelta(hours=1)).isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.json()["data"]}
        self.assertIn(inside_window.id, ids)
        self.assertNotIn(before_window.id, ids)
        self.assertNotIn(after_window.id, ids)

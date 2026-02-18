from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.db import OperationalError, close_old_connections
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Role, User, UserCode, UserRoleAssignment
from alarm.models import AlarmEvent, AlarmEventType, AlarmSettingsProfile, AlarmState, AlarmStateSnapshot, Entity
from alarm.state_machine import transitions
from alarm.tests.settings_test_utils import set_profile_settings


class ConcurrencyApiTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user(email="concurrency-user@example.com", password="pass")
        self.admin = User.objects.create_user(email="concurrency-admin@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.admin, role=role)

        self.profile = AlarmSettingsProfile.objects.filter(name="Default").first()
        if self.profile is None:
            self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        else:
            AlarmSettingsProfile.objects.update(is_active=False)
            self.profile.is_active = True
            self.profile.save(update_fields=["is_active"])

        set_profile_settings(
            self.profile,
            arming_time=30,
            delay_time=30,
            trigger_time=30,
            code_arm_required=False,
        )

        self.code_value = "1234"
        self.code = UserCode.objects.create(
            user=self.user,
            code_hash=make_password(self.code_value),
            label="Concurrency Code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )

    def _run_parallel(self, callables: list) -> tuple[list[Any], list[BaseException]]:
        barrier = threading.Barrier(len(callables))
        results: list[Any] = [None] * len(callables)
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker(index: int, fn):
            try:
                close_old_connections()
                barrier.wait(timeout=5)
                for attempt in range(4):
                    try:
                        results[index] = fn()
                        return
                    except OperationalError as exc:
                        # SQLite can throw transient lock errors under intentional
                        # concurrent writes in CI; retry briefly to assert behavior.
                        if "database table is locked" not in str(exc).lower() or attempt == 3:
                            raise
                        close_old_connections()
                        time.sleep(0.05 * (attempt + 1))
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=worker, args=(idx, fn)) for idx, fn in enumerate(callables)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        return results, errors

    def test_parallel_arm_requests_have_one_success_and_one_conflict(self):
        set_profile_settings(self.profile, arming_time=30, code_arm_required=False)
        transitions.disarm(reason="test_setup")

        arm_url = reverse("alarm-arm")
        baseline = AlarmEvent.objects.filter(
            event_type=AlarmEventType.STATE_CHANGED,
            state_from=AlarmState.DISARMED,
            state_to=AlarmState.ARMING,
        ).count()

        def call_arm():
            client = APIClient()
            client.force_authenticate(self.user)
            response = client.post(arm_url, data={"target_state": AlarmState.ARMED_AWAY}, format="json")
            return response.status_code

        statuses, errors = self._run_parallel([call_arm, call_arm])
        self.assertEqual(errors, [])
        self.assertCountEqual(statuses, [200, 409])

        snapshot = AlarmStateSnapshot.objects.first()
        assert snapshot is not None
        self.assertEqual(snapshot.current_state, AlarmState.ARMING)

        after = AlarmEvent.objects.filter(
            event_type=AlarmEventType.STATE_CHANGED,
            state_from=AlarmState.DISARMED,
            state_to=AlarmState.ARMING,
        ).count()
        self.assertEqual(after - baseline, 1)

    def test_parallel_disarm_requests_transition_once_and_end_disarmed(self):
        set_profile_settings(self.profile, arming_time=0, code_arm_required=False)
        transitions.disarm(reason="test_setup")
        transitions.arm(target_state=AlarmState.ARMED_HOME, user=self.user, reason="test_arm")

        disarm_url = reverse("alarm-disarm")
        baseline = AlarmEvent.objects.filter(
            event_type=AlarmEventType.DISARMED,
            state_from=AlarmState.ARMED_HOME,
            state_to=AlarmState.DISARMED,
        ).count()

        def call_disarm():
            client = APIClient()
            client.force_authenticate(self.user)
            response = client.post(disarm_url, data={"code": self.code_value}, format="json")
            return response.status_code

        statuses, errors = self._run_parallel([call_disarm, call_disarm])
        self.assertEqual(errors, [])
        self.assertEqual(statuses, [200, 200])

        snapshot = AlarmStateSnapshot.objects.first()
        assert snapshot is not None
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

        after = AlarmEvent.objects.filter(
            event_type=AlarmEventType.DISARMED,
            state_from=AlarmState.ARMED_HOME,
            state_to=AlarmState.DISARMED,
        ).count()
        self.assertEqual(after - baseline, 1)

    def test_parallel_cancel_arming_requests_have_one_success_and_one_conflict(self):
        set_profile_settings(self.profile, arming_time=30, code_arm_required=False)
        transitions.disarm(reason="test_setup")
        transitions.arm(target_state=AlarmState.ARMED_AWAY, user=self.user, reason="test_arm")

        cancel_url = reverse("alarm-cancel-arming")
        baseline = AlarmEvent.objects.filter(
            event_type=AlarmEventType.DISARMED,
            state_from=AlarmState.ARMING,
            state_to=AlarmState.DISARMED,
        ).count()

        def call_cancel():
            client = APIClient()
            client.force_authenticate(self.user)
            response = client.post(cancel_url, data={}, format="json")
            return response.status_code

        statuses, errors = self._run_parallel([call_cancel, call_cancel])
        self.assertEqual(errors, [])
        self.assertCountEqual(statuses, [200, 409])

        snapshot = AlarmStateSnapshot.objects.first()
        assert snapshot is not None
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

        after = AlarmEvent.objects.filter(
            event_type=AlarmEventType.DISARMED,
            state_from=AlarmState.ARMING,
            state_to=AlarmState.DISARMED,
        ).count()
        self.assertEqual(after - baseline, 1)

    def test_parallel_profile_activation_keeps_exactly_one_active_profile(self):
        AlarmSettingsProfile.objects.all().delete()
        initial = AlarmSettingsProfile.objects.create(name="Initial", is_active=True)
        profile_one = AlarmSettingsProfile.objects.create(name="One", is_active=False)
        profile_two = AlarmSettingsProfile.objects.create(name="Two", is_active=False)

        activate_one = reverse("alarm-settings-profile-activate", kwargs={"profile_id": profile_one.id})
        activate_two = reverse("alarm-settings-profile-activate", kwargs={"profile_id": profile_two.id})

        def call_activate(url: str):
            client = APIClient()
            client.force_authenticate(self.admin)
            response = client.post(url, data={}, format="json")
            return response.status_code

        statuses, errors = self._run_parallel(
            [
                lambda: call_activate(activate_one),
                lambda: call_activate(activate_two),
            ]
        )
        self.assertEqual(errors, [])
        self.assertEqual(statuses, [200, 200])

        active_ids = list(AlarmSettingsProfile.objects.filter(is_active=True).values_list("id", flat=True))
        self.assertEqual(len(active_ids), 1)
        self.assertIn(active_ids[0], {profile_one.id, profile_two.id})

        initial.refresh_from_db()
        self.assertEqual(initial.is_active, False)

    def test_parallel_entity_sync_requests_do_not_duplicate_entities(self):
        sync_url = reverse("alarm-entities-sync")

        class _Gateway:
            def ensure_available(self):
                return None

            def list_entities(self):
                return [
                    {
                        "entity_id": "binary_sensor.front_door",
                        "domain": "binary_sensor",
                        "name": "Front Door",
                        "state": "off",
                    }
                ]

        with patch("alarm.views.entities.ha_gateway", _Gateway()):
            def call_sync():
                client = APIClient()
                client.force_authenticate(self.user)
                response = client.post(sync_url, data={}, format="json")
                return response.status_code

            statuses, errors = self._run_parallel([call_sync, call_sync])

        self.assertEqual(errors, [])
        self.assertEqual(statuses, [200, 200])
        self.assertEqual(Entity.objects.filter(entity_id="binary_sensor.front_door").count(), 1)

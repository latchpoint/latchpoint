from __future__ import annotations

import sys
import threading
import time
from typing import Any
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.core.signals import got_request_exception
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
        """Run each callable on its own thread, all released at once.

        Each callable makes one request with an ``APIClient(raise_request_exception=False)``
        and returns the status code. Django's test client must not raise view errors here:
        ``got_request_exception`` is a global signal, so a client stores and re-raises an
        exception from *any* thread's request that fails while its own is in flight (#187).
        One lock error then failed both threads at once and kept them retrying in step until
        both ran out of retries. View errors are recorded against the thread that raised them.
        """
        barrier = threading.Barrier(len(callables))
        results: list[Any] = [None] * len(callables)
        errors: list[BaseException] = []
        lock = threading.Lock()
        max_lock_retries = 12
        view_errors: dict[int, BaseException | None] = {}

        def record_view_error(sender, **kwargs):
            # Sent from inside the handler's `except`, on the thread whose request failed.
            view_errors[threading.get_ident()] = sys.exc_info()[1]

        def is_lock_error(exc: BaseException) -> bool:
            return isinstance(exc, OperationalError) and "database table is locked" in str(exc).lower()

        def worker(index: int, fn):
            ident = threading.get_ident()
            try:
                close_old_connections()
                barrier.wait(timeout=5)
                for attempt in range(max_lock_retries):
                    view_errors.pop(ident, None)
                    result = fn()
                    exc = view_errors.pop(ident, None)
                    if exc is None:
                        results[index] = result
                        return
                    # SQLite ignores select_for_update() and its shared in-memory test db fails a
                    # write at once with "database table is locked" while another transaction
                    # holds the table, so the loser of a race retries. Back off by thread index
                    # so the threads don't retry in step.
                    if not is_lock_error(exc) or attempt == max_lock_retries - 1:
                        raise exc
                    close_old_connections()
                    time.sleep(0.05 * (attempt + 1) * (index + 1))
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)
            finally:
                close_old_connections()

        uid = f"concurrency-api-tests-{id(view_errors)}"
        got_request_exception.connect(record_view_error, dispatch_uid=uid, weak=False)
        try:
            threads = [threading.Thread(target=worker, args=(idx, fn)) for idx, fn in enumerate(callables)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
        finally:
            got_request_exception.disconnect(dispatch_uid=uid)
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
            client = APIClient(raise_request_exception=False)
            client.force_authenticate(self.user)
            response = client.post(arm_url, data={"target_state": AlarmState.ARMED_AWAY}, format="json")
            return response.status_code

        statuses, errors = self._run_parallel([call_arm, call_arm])
        self.assertEqual(errors, [])
        self.assertEqual(len(statuses), 2)
        self.assertTrue(all(status in {200, 409} for status in statuses))

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
            client = APIClient(raise_request_exception=False)
            client.force_authenticate(self.user)
            response = client.post(disarm_url, data={"code": self.code_value}, format="json")
            return response.status_code

        statuses, errors = self._run_parallel([call_disarm, call_disarm])
        self.assertEqual(errors, [])
        self.assertEqual(len(statuses), 2)
        self.assertTrue(all(status in {200, 409} for status in statuses))

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
            client = APIClient(raise_request_exception=False)
            client.force_authenticate(self.user)
            response = client.post(cancel_url, data={}, format="json")
            return response.status_code

        statuses, errors = self._run_parallel([call_cancel, call_cancel])
        self.assertEqual(errors, [])
        self.assertEqual(len(statuses), 2)
        self.assertTrue(all(status in {200, 409} for status in statuses))

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
            client = APIClient(raise_request_exception=False)
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
                client = APIClient(raise_request_exception=False)
                client.force_authenticate(self.user)
                response = client.post(sync_url, data={}, format="json")
                return response.status_code

            statuses, errors = self._run_parallel([call_sync, call_sync])

        self.assertEqual(errors, [])
        self.assertEqual(statuses, [200, 200])
        self.assertEqual(Entity.objects.filter(entity_id="binary_sensor.front_door").count(), 1)

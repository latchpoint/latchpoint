"""Deleting a user who still has door codes on a lock is refused (issue #235).

The delete would cascade their codes away without clearing them off the locks,
so their PINs would keep opening the doors with nothing tracking them.
Deleting the codes first clears them off the locks the normal way.
"""

from __future__ import annotations

from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import ProtectedError
from django.urls import reverse

from accounts.models import User
from alarm.models import Entity
from locks.models import DoorCode, DoorCodeLockAssignment
from locks.tests.test_lock_push import AVAILABLE_BEFORE_SET, ClearFailingGateway, _TwoLockUpdateTestBase
from locks.tests.test_tracking_integrity import _holding, _timeouts
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_push as lock_push_uc

REFUSED = "Delete their door codes first"


class _UserDeleteTestBase(_TwoLockUpdateTestBase):
    def setUp(self):
        super().setUp()
        self.member = User.objects.create_user(email="member@example.com", password="pass")
        self.gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True)

    def _member_code(self, lock_entity_ids: list[str], *, label: str = "Front") -> DoorCode:
        return door_codes_uc.create_door_code(
            user=self.member,
            raw_code=self.PIN,
            label=label,
            lock_entity_ids=lock_entity_ids,
            actor_user=self.user,
            zwavejs=self.gateway,
        )

    def _slots_held(self) -> list[tuple[int, int]]:
        """(node, slot) of every slot holding a PIN on the fake locks, without the PINs."""
        return sorted(self.gateway._lock_codes)

    def _assert_nothing_deleted(self, code: DoorCode, *, assigned: bool = True) -> None:
        self.assertTrue(User.objects.filter(id=self.member.id).exists())
        self.assertTrue(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(DoorCodeLockAssignment.objects.filter(door_code=code).exists(), assigned)


class OrmUserDeleteTests(_UserDeleteTestBase):
    def test_deleting_a_user_with_a_code_on_a_lock_raises_protected_error(self):
        code = self._member_code([self.BACK])
        self.assertEqual(self._slots_held(), [(12, 1)])

        with self.assertRaises(ProtectedError) as ctx, transaction.atomic():
            self.member.delete()

        self.assertIn(REFUSED, ctx.exception.args[0])
        self.assertIn("member@example.com", ctx.exception.args[0])
        self.assertEqual(set(ctx.exception.protected_objects), {code})
        self._assert_nothing_deleted(code)
        self.assertEqual(self._slots_held(), [(12, 1)])

    def test_a_queryset_delete_is_refused_and_deletes_none_of_the_users(self):
        code = self._member_code([self.BACK])
        other = User.objects.create_user(email="other@example.com", password="pass")

        with self.assertRaises(ProtectedError), transaction.atomic():
            User.objects.filter(id__in=[self.member.id, other.id]).delete()

        self._assert_nothing_deleted(code)
        self.assertTrue(User.objects.filter(id=other.id).exists())

    def test_a_code_assigned_to_a_lock_but_not_pushed_yet_still_blocks(self):
        code = self._member_code([])
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK)

        with self.assertRaises(ProtectedError), transaction.atomic():
            self.member.delete()

        self._assert_nothing_deleted(code)

    def test_a_user_with_only_lock_less_codes_can_be_deleted(self):
        code = self._member_code([])

        self.member.delete()

        self.assertFalse(User.objects.filter(id=self.member.id).exists())
        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())

    def test_after_their_codes_are_deleted_the_user_can_be_deleted(self):
        code = self._member_code([self.BACK, self.SIDE])
        self.assertEqual(self._slots_held(), [(12, 1), (13, 1)])

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=self.gateway)
        self.assertEqual(self._slots_held(), [])

        self.member.delete()

        self.assertFalse(User.objects.filter(id=self.member.id).exists())


class DroppedLockUserDeleteTests(_UserDeleteTestBase):
    """A code dropped from its only lock can still hold its PIN there with no assignment left (PR #236 review)."""

    def _code_dropped_from_side(self, *, drop_readback: list) -> DoorCode:
        """A code whose push to Side landed but every readback timed out, then dropped from Side.

        ``drop_readback`` is what Side answers when the drop reads the slot back.
        """
        self.gateway._get_scripts = {13: [AVAILABLE_BEFORE_SET, *_timeouts()]}
        code = self._member_code([self.SIDE])
        self.assertEqual(self._slots(code), {self.SIDE: None})
        self.assertEqual(self._slots_held(), [(13, 1)])
        self.gateway._get_scripts = {13: list(drop_readback)}

        door_codes_uc.update_door_code(
            code=door_codes_uc.get_door_code_for_read(code_id=code.id),
            changes={"lock_entity_ids": []},
            actor_user=self.user,
            zwavejs=self.gateway,
        )

        self.assertFalse(DoorCodeLockAssignment.objects.filter(door_code=code).exists())
        self.assertEqual(self._slots_held(), [(13, 1)])
        return code

    # A real drop leaves both an unconfirmed attempt and a clear failure on Side,
    # so each of the next two tests hides the other one to check its own alone.

    def test_an_unconfirmed_push_on_a_dropped_lock_blocks_the_delete(self):
        code = self._code_dropped_from_side(drop_readback=_timeouts())
        self.assertEqual(lock_push_uc.unconfirmed_attempt_lock_entity_ids(door_code=code), [self.SIDE])

        with (
            patch.object(lock_push_uc, "unresolved_clear_failures", return_value=[]),
            self.assertRaises(ProtectedError) as ctx,
            transaction.atomic(),
        ):
            self.member.delete()

        self.assertEqual(set(ctx.exception.protected_objects), {code})
        self._assert_nothing_deleted(code, assigned=False)

    def test_an_open_clear_failure_on_a_dropped_lock_blocks_the_delete(self):
        # Side answers the drop's readback with the PIN, but the clear times out.
        self.gateway.clear_fails_on = {13}
        code = self._code_dropped_from_side(drop_readback=[_holding(self.PIN)])
        self.assertEqual(
            [f.lock_entity_id for f in lock_push_uc.unresolved_clear_failures(door_code=code)], [self.SIDE]
        )

        with (
            patch.object(lock_push_uc, "unconfirmed_attempt_lock_entity_ids", return_value=[]),
            self.assertRaises(ProtectedError) as ctx,
            transaction.atomic(),
        ):
            self.member.delete()

        self.assertEqual(set(ctx.exception.protected_objects), {code})
        self._assert_nothing_deleted(code, assigned=False)

    def test_the_admin_refuses_a_code_left_on_a_dropped_lock(self):
        code = self._code_dropped_from_side(drop_readback=_timeouts())
        self.client.force_login(self.user)

        response = self.client.post(reverse("admin:accounts_user_delete", args=[self.member.pk]), {"post": "yes"})

        self.assertContains(response, REFUSED)
        self._assert_nothing_deleted(code, assigned=False)

    def test_once_deleting_the_code_clears_the_dropped_lock_the_user_can_be_deleted(self):
        code = self._code_dropped_from_side(drop_readback=_timeouts())
        self.gateway._get_scripts = {13: [_holding(self.PIN)]}

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=self.gateway)
        self.assertEqual(self._slots_held(), [])

        self.member.delete()

        self.assertFalse(User.objects.filter(id=self.member.id).exists())


class AdminUserDeleteTests(_UserDeleteTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def _delete_url(self, user: User) -> str:
        return reverse("admin:accounts_user_delete", args=[user.pk])

    def test_the_delete_page_refuses_with_the_message(self):
        code = self._member_code([self.BACK], label="Front gate")

        response = self.client.get(self._delete_url(self.member))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, REFUSED)
        self.assertContains(response, "Front gate")
        # The page lists the codes as protected, so it has no confirm button.
        self.assertTrue(response.context["protected"])
        self._assert_nothing_deleted(code)

    def test_confirming_the_delete_is_refused(self):
        code = self._member_code([self.BACK])

        response = self.client.post(self._delete_url(self.member), {"post": "yes"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, REFUSED)
        self._assert_nothing_deleted(code)
        self.assertEqual(self._slots_held(), [(12, 1)])

    def test_a_code_on_two_locks_is_listed_once(self):
        self._member_code([self.BACK, self.SIDE], label="Front gate")

        response = self.client.get(self._delete_url(self.member))

        self.assertEqual(len(response.context["protected"]), 1)
        self.assertIn("Front gate", response.context["protected"][0])

    def test_bulk_delete_selected_is_refused_with_the_message(self):
        code = self._member_code([self.BACK])
        # Sorts before member@ in the admin's email ordering, so a check of only
        # the first selected user would miss the one with the code.
        other = User.objects.create_user(email="another@example.com", password="pass")
        selected = {"action": "delete_selected", "_selected_action": [other.pk, self.member.pk]}
        url = reverse("admin:accounts_user_changelist")

        for data in (selected, {**selected, "post": "yes"}):
            response = self.client.post(url, data)

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, REFUSED)
            self.assertTrue(response.context["protected"])
        self._assert_nothing_deleted(code)
        self.assertTrue(User.objects.filter(id=other.id).exists())

    def test_a_user_with_only_lock_less_codes_is_deleted(self):
        code = self._member_code([])

        response = self.client.post(self._delete_url(self.member), {"post": "yes"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(id=self.member.id).exists())
        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())


class SeedTestHomeUserDeleteTests(_UserDeleteTestBase):
    def test_seeding_over_a_code_on_a_lock_fails_with_the_message_and_deletes_nothing(self):
        from alarm.management.commands import seed_test_home

        code = self._member_code([self.BACK])
        entities = Entity.objects.count()
        config = seed_test_home.SeedEntitiesConfig(
            entry_entity_id="binary_sensor.front", motion_entity_id="binary_sensor.hall", extra_entity_ids=[]
        )

        with (
            patch.object(seed_test_home, "_load_entities_config", return_value=config),
            patch.object(seed_test_home.home_assistant, "get_status"),
            self.assertRaises(CommandError) as ctx,
        ):
            call_command("seed_test_home", no_ha_sync=True)

        self.assertIn(REFUSED, str(ctx.exception))
        self._assert_nothing_deleted(code)
        self.assertEqual(Entity.objects.count(), entities)

"""Deleting a user who still has door codes on a lock is refused (issue #235).

The delete would cascade their codes away without clearing them off the locks,
so their PINs would keep opening the doors with nothing tracking them.
Deleting the codes first clears them off the locks the normal way.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import ProtectedError
from django.urls import reverse

from accounts.models import User
from locks.models import DoorCode, DoorCodeLockAssignment
from locks.tests.test_lock_push import ClearFailingGateway, _TwoLockUpdateTestBase
from locks.use_cases import door_codes as door_codes_uc

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

    def _assert_nothing_deleted(self, code: DoorCode) -> None:
        self.assertTrue(User.objects.filter(id=self.member.id).exists())
        self.assertTrue(DoorCode.objects.filter(id=code.id).exists())
        self.assertTrue(DoorCodeLockAssignment.objects.filter(door_code=code).exists())


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

    def test_bulk_delete_selected_is_refused_with_the_message(self):
        code = self._member_code([self.BACK])
        other = User.objects.create_user(email="other@example.com", password="pass")
        selected = {"action": "delete_selected", "_selected_action": [self.member.pk, other.pk]}
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

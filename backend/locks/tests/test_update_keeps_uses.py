"""An update doesn't write back a stale use count (issue #145).

``_hold_door_code_locks`` reads the code once it holds the ``lock_sync:``
locks, and ``_update_door_code_locked`` saves it later. A keypad use counted in
between (``F("uses_count") + 1``, no ``lock_sync:`` lock) used to be overwritten
by that save. This only uses what main already had, so it fails there.
"""

from __future__ import annotations

from unittest.mock import patch

from django.db.models import F
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.models import Entity
from alarm.tests.settings_test_utils import EncryptionTestMixin
from locks.models import DoorCode, DoorCodeLockAssignment
from locks.use_cases import door_codes as door_codes_uc

BACK = "lock.back_door"


class UpdateKeepsConcurrentUseTests(EncryptionTestMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(email="admin@example.com", password="pass")
        Entity.objects.create(
            entity_id=BACK, domain="lock", name="Back Door", attributes={"zwavejs": {"node_id": 12}}, source="x"
        )
        self.code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("4321"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            label="Guest",
            uses_count=2,
            push_state=DoorCode.PushState.PUSHED,
        )
        DoorCodeLockAssignment.objects.create(
            door_code=self.code, lock_entity_id=BACK, slot_index=3, push_state=DoorCode.PushState.PUSHED
        )

    def test_a_use_counted_between_the_read_and_the_save_is_kept(self):
        used_at = timezone.now()
        real_refuse = door_codes_uc._refuse_lock_changes_leaving_no_locks

        def use_lands_now(*, code, changes):
            # The first thing the locked update does after the read under the locks.
            DoorCode.objects.filter(id=code.id).update(
                uses_count=F("uses_count") + 1, last_used_at=used_at, last_used_lock=BACK
            )
            return real_refuse(code=code, changes=changes)

        with patch.object(door_codes_uc, "_refuse_lock_changes_leaving_no_locks", use_lands_now):
            updated = door_codes_uc.update_door_code(
                code=self.code, changes={"label": "Front gate guest"}, actor_user=self.user
            )

        fresh = DoorCode.objects.get(id=self.code.id)
        self.assertEqual(fresh.label, "Front gate guest")
        self.assertEqual(fresh.uses_count, 3)
        self.assertEqual(fresh.last_used_at, used_at)
        self.assertEqual(fresh.last_used_lock, BACK)
        # The returned code has the count too, so the response shows it.
        self.assertEqual(updated.uses_count, 3)

    def test_an_update_still_writes_its_own_fields(self):
        door_codes_uc.update_door_code(
            code=self.code, changes={"label": "New", "max_uses": 4, "is_active": False}, actor_user=self.user
        )
        fresh = DoorCode.objects.get(id=self.code.id)
        self.assertEqual((fresh.label, fresh.max_uses, fresh.is_active, fresh.uses_count), ("New", 4, False, 2))

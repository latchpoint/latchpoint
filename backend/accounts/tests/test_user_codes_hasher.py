from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone

from django.contrib.auth.hashers import check_password, get_hasher, make_password
from django.test import TestCase

from accounts.hashers import UserCodeArgon2Hasher
from accounts.models import User, UserCode
from accounts.use_cases import code_validation
from accounts.use_cases.user_codes import create_user_code, update_user_code


class UserCodeArgon2HasherRegistrationTests(TestCase):
    def test_hasher_is_registered_under_argon2_pin_algorithm(self):
        hasher = get_hasher("argon2-pin")
        self.assertIsInstance(hasher, UserCodeArgon2Hasher)

    def test_reduced_cost_params(self):
        hasher = get_hasher("argon2-pin")
        self.assertEqual(hasher.time_cost, 1)
        self.assertEqual(hasher.memory_cost, 8 * 1024)
        self.assertEqual(hasher.parallelism, 2)


class UserCodeHasherUsageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="hasher@example.com", password="pass")

    def test_create_user_code_routes_through_argon2_pin(self):
        code = create_user_code(user=self.user, raw_code="1234", label="kitchen")
        self.assertTrue(
            code.code_hash.startswith("argon2-pin$"),
            f"expected argon2-pin$ prefix, got: {code.code_hash[:30]}",
        )

    def test_update_user_code_rotates_to_argon2_pin(self):
        code = create_user_code(user=self.user, raw_code="1234")
        original_hash = code.code_hash
        update_user_code(code=code, changes={"code": "5678"})
        code.refresh_from_db()
        self.assertNotEqual(code.code_hash, original_hash)
        self.assertTrue(code.code_hash.startswith("argon2-pin$"))

    def test_check_password_round_trips_new_hash(self):
        hashed = make_password("4242", hasher="argon2-pin")
        self.assertTrue(hashed.startswith("argon2-pin$"))
        self.assertTrue(check_password("4242", hashed))
        self.assertFalse(check_password("0000", hashed))

    def test_validates_new_argon2_pin_code_via_use_case(self):
        code = create_user_code(user=self.user, raw_code="9876")
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_user_code(user=self.user, raw_code="9876", now=now)
        self.assertEqual(result.code.id, code.id)

    def test_legacy_argon2_hash_still_verifies(self):
        # Existing rows in production were hashed under the default 'argon2'
        # algorithm. Verify those continue to validate after the new hasher
        # is added - no migration required.
        legacy_hash = make_password("1234")
        self.assertTrue(legacy_hash.startswith("argon2$"))
        UserCode.objects.create(
            user=self.user,
            code_hash=legacy_hash,
            label="legacy",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_user_code(user=self.user, raw_code="1234", now=now)
        self.assertTrue(result.code.code_hash.startswith("argon2$"))

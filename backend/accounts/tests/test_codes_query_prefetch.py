from __future__ import annotations

from django.test import TestCase

from accounts.models import User, UserCode, UserCodeAllowedState
from accounts.serializers import UserCodeSerializer


class CodesPrefetchRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="prefetch@example.com", password="pass")

    def test_user_code_serializer_requires_allowed_states_prefetch(self):
        code = UserCode.objects.create(
            user=self.user,
            code_hash="not-used-here",
            label="Test",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        UserCodeAllowedState.objects.create(code=code, state=UserCodeAllowedState.AlarmState.ARMED_AWAY)

        with self.assertRaises(RuntimeError):
            UserCodeSerializer(code).data

        code_prefetched = (
            UserCode.objects.select_related("user")
            .prefetch_related("allowed_states")
            .get(id=code.id)
        )
        payload = UserCodeSerializer(code_prefetched).data
        self.assertEqual(payload["allowed_states"], [UserCodeAllowedState.AlarmState.ARMED_AWAY])


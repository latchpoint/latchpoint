from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User, UserCode, UserCodeAllowedState


class TestCodesListDetailQueries(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="codes-queries@example.com", password="pass")
        self.admin = User.objects.create_superuser(email="codes-admin@example.com", password="pass")
        self.client = APIClient()

    def test_codes_list_is_constant_queries(self):
        first = UserCode.objects.create(
            user=self.user,
            code_hash=make_password("1111"),
            label="First",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        UserCodeAllowedState.objects.create(code=first, state=UserCodeAllowedState.AlarmState.ARMED_HOME)
        UserCodeAllowedState.objects.create(code=first, state=UserCodeAllowedState.AlarmState.ARMED_AWAY)

        second = UserCode.objects.create(
            user=self.user,
            code_hash=make_password("2222"),
            label="Second",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        UserCodeAllowedState.objects.create(code=second, state=UserCodeAllowedState.AlarmState.ARMED_NIGHT)

        self.client.force_authenticate(self.user)
        url = reverse("codes")
        with self.assertNumQueries(2):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["data"]), 2)
        self.assertIn("allowed_states", body["data"][0])

    def test_code_detail_is_constant_queries(self):
        code = UserCode.objects.create(
            user=self.user,
            code_hash=make_password("3333"),
            label="Detail",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        UserCodeAllowedState.objects.create(code=code, state=UserCodeAllowedState.AlarmState.ARMED_HOME)

        self.client.force_authenticate(self.admin)
        url = reverse("code-detail", args=[code.id])
        with self.assertNumQueries(2):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["id"], code.id)
        self.assertEqual(body["data"]["allowed_states"], ["armed_home"])

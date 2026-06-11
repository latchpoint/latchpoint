from __future__ import annotations

from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from accounts.models import User


class TokenExpiryTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="tok@example.com", password="pass")

    def _bearer_client(self, key: str) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
        return client

    @staticmethod
    def _backdate(token: Token, seconds: int) -> None:
        # ``created`` is auto_now_add, so bypass it with a queryset update.
        Token.objects.filter(pk=token.pk).update(created=timezone.now() - timedelta(seconds=seconds))

    @override_settings(AUTH_TOKEN_TTL_SECONDS=3600)
    def test_fresh_token_accepted(self):
        token = Token.objects.create(user=self.user)
        resp = self._bearer_client(token.key).get(reverse("users-me"))
        self.assertEqual(resp.status_code, 200)

    @override_settings(AUTH_TOKEN_TTL_SECONDS=3600)
    def test_expired_token_rejected_and_deleted(self):
        token = Token.objects.create(user=self.user)
        self._backdate(token, 7200)

        resp = self._bearer_client(token.key).get(reverse("users-me"))
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(Token.objects.filter(pk=token.pk).exists())

    @override_settings(AUTH_TOKEN_TTL_SECONDS=0)
    def test_ttl_zero_disables_expiry(self):
        token = Token.objects.create(user=self.user)
        self._backdate(token, 365 * 24 * 3600)
        resp = self._bearer_client(token.key).get(reverse("users-me"))
        self.assertEqual(resp.status_code, 200)

    @override_settings(AUTH_TOKEN_TTL_SECONDS=3600)
    def test_login_rotates_expired_token(self):
        token = Token.objects.create(user=self.user)
        old_key = token.key
        self._backdate(token, 7200)

        resp = self.client.post(
            reverse("auth-login"),
            data={"email": "tok@example.com", "password": "pass"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        new_key = resp.json()["data"]["accessToken"]
        self.assertNotEqual(new_key, old_key)
        self.assertFalse(Token.objects.filter(key=old_key).exists())

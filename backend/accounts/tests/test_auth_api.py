from __future__ import annotations

from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import User


class AuthApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="auth@example.com", password="pass")

    def test_csrf_sets_cookie(self):
        url = reverse("auth-csrf")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrfToken", response.json()["data"])
        self.assertIn("csrftoken", response.cookies)

    def test_login_returns_token_payload(self):
        url = reverse("auth-login")
        response = self.client.post(url, data={"email": "auth@example.com", "password": "pass"}, format="json")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("accessToken", payload)
        self.assertIn("refreshToken", payload)
        self.assertEqual(payload["accessToken"], payload["refreshToken"])
        self.assertEqual(payload["user"]["email"], "auth@example.com")
        self.assertIn("sessionid", response.cookies)

        me_url = reverse("users-me")
        me_response = self.client.get(me_url)
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["data"]["email"], "auth@example.com")

    def test_login_rejects_invalid_credentials(self):
        url = reverse("auth-login")
        response = self.client.post(url, data={"email": "auth@example.com", "password": "wrong"}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_refresh_requires_refresh_token(self):
        url = reverse("auth-token-refresh")
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["status"], "validation_error")
        self.assertEqual(body["error"]["details"]["refresh"][0], "Missing refresh token.")

    def test_refresh_rejects_invalid_token(self):
        url = reverse("auth-token-refresh")
        response = self.client.post(url, data={"refresh": "nope"}, format="json")
        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertEqual(body["error"]["status"], "unauthorized")
        self.assertIn("Invalid refresh token.", body["error"]["message"])

    def test_refresh_returns_same_token(self):
        token = Token.objects.create(user=self.user)
        url = reverse("auth-token-refresh")
        response = self.client.post(url, data={"refresh": token.key}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["accessToken"], token.key)
        self.assertEqual(body["data"]["refreshToken"], token.key)

    def test_logout_deletes_token(self):
        login_url = reverse("auth-login")
        self.client.post(login_url, data={"email": "auth@example.com", "password": "pass"}, format="json")
        self.assertTrue(Token.objects.filter(user=self.user).exists())

        url = reverse("auth-logout")
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Token.objects.filter(user=self.user).exists())

        me_url = reverse("users-me")
        me_response = self.client.get(me_url)
        self.assertEqual(me_response.status_code, 401)

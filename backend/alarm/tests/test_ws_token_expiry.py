from __future__ import annotations

import asyncio
from datetime import timedelta

from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token

from accounts.models import User
from config.asgi import application


@override_settings(AUTH_TOKEN_TTL_SECONDS=3600)
class WsTokenExpiryTests(TransactionTestCase):
    """The WS `?token=` path honors AUTH_TOKEN_TTL_SECONDS: expired tokens resolve to
    AnonymousUser and the consumer rejects the connection (close 4401)."""

    def setUp(self):
        self.user = User.objects.create_user(email="wsexp@example.com", password="pass")
        self.token = Token.objects.create(user=self.user)

    def test_fresh_token_connects(self):
        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={self.token.key}")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.disconnect()

        asyncio.run(run())

    def test_expired_token_is_rejected(self):
        # ``created`` is auto_now_add, so backdate it past the TTL with a queryset update.
        Token.objects.filter(pk=self.token.pk).update(created=timezone.now() - timedelta(seconds=7200))

        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={self.token.key}")
            connected, _ = await communicator.connect()
            self.assertFalse(connected)
            await communicator.disconnect()

        asyncio.run(run())

from __future__ import annotations

import asyncio

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from rest_framework.authtoken.models import Token

from accounts.models import User
from alarm.log_handler import LOG_BROADCAST_GROUP
from config.asgi import application

_LOG_MESSAGE = {
    "type": "log_entry",
    "timestamp": "2026-01-01T00:00:00Z",
    "sequence": 999999,
    "payload": {"message": "internal log line", "level": "WARNING"},
}


async def _connect(token_key: str) -> WebsocketCommunicator:
    communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={token_key}")
    connected, _ = await communicator.connect()
    assert connected
    # Drain the two initial frames (alarm_state + system_status).
    await communicator.receive_json_from(timeout=1)
    await communicator.receive_json_from(timeout=1)
    return communicator


class ConsumerLogGatingTests(TransactionTestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="logadmin@example.com", password="pass", is_staff=True)
        self.member = User.objects.create_user(email="logmember@example.com", password="pass")
        self.admin_token = Token.objects.create(user=self.admin).key
        self.member_token = Token.objects.create(user=self.member).key

    def test_only_admins_receive_log_broadcasts(self):
        async def run():
            admin_comm = await _connect(self.admin_token)
            member_comm = await _connect(self.member_token)
            try:
                channel_layer = get_channel_layer()
                await channel_layer.group_send(
                    LOG_BROADCAST_GROUP,
                    {"type": "broadcast", "message": _LOG_MESSAGE},
                )

                admin_msg = await admin_comm.receive_json_from(timeout=1)
                self.assertEqual(admin_msg.get("type"), "log_entry")

                # The non-admin never joined the log group, so it gets nothing.
                self.assertTrue(await member_comm.receive_nothing(timeout=0.3))
            finally:
                await admin_comm.disconnect()
                await member_comm.disconnect()

        asyncio.run(run())

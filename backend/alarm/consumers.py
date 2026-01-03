from __future__ import annotations

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework.utils.encoders import JSONEncoder

from alarm.state_machine import transitions
from alarm.websocket import build_alarm_state_message
from alarm.system_status import get_current_system_status_message

logger = logging.getLogger(__name__)


class AlarmConsumer(AsyncJsonWebsocketConsumer):
    group_name = "alarm"

    @classmethod
    async def encode_json(cls, content):
        """Serialize websocket payloads using DRF's JSONEncoder for date/time support."""
        return json.dumps(content, cls=JSONEncoder)

    @database_sync_to_async
    def _get_current_alarm_state_message(self):
        """Fetch the current alarm snapshot and serialize it for websocket delivery."""
        snapshot = transitions.get_current_snapshot(process_timers=False)
        return build_alarm_state_message(snapshot=snapshot)

    async def connect(self):
        """Authenticate and subscribe the client to alarm broadcasts, then send initial snapshots."""
        user = self.scope.get("user")
        if not user or getattr(user, "is_anonymous", True):
            logger.info("WS connect: rejected anonymous user")
            await self.close(code=4401)
            return
        logger.info("WS connect: accepted user_id=%s", getattr(user, "id", None))
        await self.accept()
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        try:
            await self.send_json(await self._get_current_alarm_state_message())
        except Exception:
            logger.exception("WS connect: failed to send initial alarm_state")
        try:
            await self.send_json(await database_sync_to_async(get_current_system_status_message)())
        except Exception:
            logger.exception("WS connect: failed to send initial system_status")

    async def receive_json(self, content, **kwargs):
        """Handle simple client messages (ping/pong)."""
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def disconnect(self, code):
        """Unsubscribe the client from broadcasts and log disconnect."""
        user = self.scope.get("user")
        try:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        except Exception:
            logger.exception("WS disconnect: group_discard failed")
        logger.info("WS disconnect: code=%s user_id=%s", code, getattr(user, "id", None) if user else None)

    async def broadcast(self, event):
        """Receive a group broadcast event and forward it to the websocket client."""
        message = event.get("message")
        if message is not None:
            await self.send_json(message)

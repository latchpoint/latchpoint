from __future__ import annotations

import asyncio
from unittest.mock import patch

from channels.testing import WebsocketCommunicator
from channels.db import database_sync_to_async
from django.test import Client
from django.test import TransactionTestCase
from rest_framework.authtoken.models import Token

from accounts.models import User
from config.asgi import application
from alarm.models import AlarmState
from alarm.state_machine import transitions


class AlarmWebSocketTests(TransactionTestCase):
    def test_websocket_requires_auth(self):
        async def run():
            communicator = WebsocketCommunicator(application, "/ws/alarm/")
            try:
                connected, _ = await communicator.connect()
                self.assertFalse(connected)
            finally:
                await communicator.disconnect()

        asyncio.run(run())

    def test_websocket_connects_with_token(self):
        user = User.objects.create_user(email="ws@example.com", password="pass")
        token = Token.objects.create(user=user)

        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={token.key}")
            try:
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
            finally:
                await communicator.disconnect()

        asyncio.run(run())

    def test_websocket_connects_with_session_cookie(self):
        user = User.objects.create_user(email="wssession@example.com", password="pass")
        client = Client()
        client.force_login(user)
        sessionid = client.cookies.get("sessionid").value
        cookie_header = f"sessionid={sessionid}".encode("utf-8")

        async def run():
            communicator = WebsocketCommunicator(
                application,
                "/ws/alarm/",
                headers=[(b"cookie", cookie_header)],
            )
            try:
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
            finally:
                await communicator.disconnect()

        asyncio.run(run())

    def test_websocket_rejects_invalid_token(self):
        async def run():
            communicator = WebsocketCommunicator(application, "/ws/alarm/?token=not-a-real-token")
            try:
                connected, _ = await communicator.connect()
                self.assertFalse(connected)
            finally:
                await communicator.disconnect()

        asyncio.run(run())

    def test_websocket_ping_pong(self):
        user = User.objects.create_user(email="wsping@example.com", password="pass")
        token = Token.objects.create(user=user)

        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={token.key}")
            try:
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
                await communicator.send_json_to({"type": "ping"})
                # WS sends initial state on connect; drain until pong.
                for _ in range(3):
                    msg = await communicator.receive_json_from(timeout=1)
                    if msg == {"type": "pong"}:
                        break
                self.assertEqual(msg, {"type": "pong"})
            finally:
                await communicator.disconnect()

        asyncio.run(run())

    def test_websocket_sends_initial_alarm_state_on_connect(self):
        user = User.objects.create_user(email="wsinitial@example.com", password="pass")
        token = Token.objects.create(user=user)

        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={token.key}")
            try:
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
                msg = await communicator.receive_json_from(timeout=1)
                self.assertEqual(msg.get("type"), "alarm_state")
            finally:
                await communicator.disconnect()

        asyncio.run(run())

    def test_websocket_sends_initial_system_status_on_connect(self):
        user = User.objects.create_user(email="wssystem@example.com", password="pass")
        token = Token.objects.create(user=user)

        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={token.key}")
            try:
                connected, _ = await communicator.connect()
                self.assertTrue(connected)

                # WS sends alarm_state + system_status on connect; order should be stable,
                # but accept either to avoid coupling test to implementation detail.
                first = await communicator.receive_json_from(timeout=1)
                second = await communicator.receive_json_from(timeout=1)
                types = {first.get("type"), second.get("type")}
                self.assertIn("alarm_state", types)
                self.assertIn("system_status", types)
            finally:
                await communicator.disconnect()

        asyncio.run(run())

    def test_websocket_initial_messages_have_contract_and_sequence(self):
        user = User.objects.create_user(email="wscontract@example.com", password="pass")
        token = Token.objects.create(user=user)

        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={token.key}")
            try:
                connected, _ = await communicator.connect()
                self.assertTrue(connected)

                alarm_msg = await communicator.receive_json_from(timeout=1)
                system_msg = await communicator.receive_json_from(timeout=1)

                self.assertEqual(alarm_msg.get("type"), "alarm_state")
                self.assertEqual(system_msg.get("type"), "system_status")

                self.assertIsInstance(alarm_msg.get("sequence"), int)
                self.assertIsInstance(system_msg.get("sequence"), int)
                self.assertGreater(alarm_msg["sequence"], 0)
                self.assertGreater(system_msg["sequence"], 0)

                alarm_payload = alarm_msg.get("payload") or {}
                self.assertIn("state", alarm_payload)
                self.assertIn("effective_settings", alarm_payload)
                state = alarm_payload.get("state") or {}
                for key in (
                    "id",
                    "current_state",
                    "previous_state",
                    "settings_profile",
                    "entered_at",
                    "timing_snapshot",
                ):
                    self.assertIn(key, state)

                effective = alarm_payload.get("effective_settings") or {}
                for key in ("delay_time", "arming_time", "trigger_time"):
                    self.assertIn(key, effective)

                system_payload = system_msg.get("payload") or {}
                for key in ("home_assistant", "mqtt", "zwavejs", "zigbee2mqtt", "frigate"):
                    self.assertIn(key, system_payload)
            finally:
                await communicator.disconnect()

        asyncio.run(run())

    def test_websocket_receives_alarm_state_updates(self):
        user = User.objects.create_user(email="wsstate@example.com", password="pass")
        token = Token.objects.create(user=user)

        @database_sync_to_async
        def arm_alarm():
            transitions.disarm(reason="test_setup")
            transitions.arm(target_state=AlarmState.ARMED_HOME, reason="test_arm")

        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={token.key}")
            try:
                connected, _ = await communicator.connect()
                self.assertTrue(connected)

                # Drain both initial messages (alarm_state + system_status)
                await communicator.receive_json_from(timeout=1)
                await communicator.receive_json_from(timeout=1)

                await arm_alarm()

                msg = await communicator.receive_json_from(timeout=1)
                self.assertEqual(msg.get("type"), "alarm_state")
                payload = msg.get("payload") or {}
                self.assertIn(
                    payload.get("state", {}).get("current_state"),
                    {AlarmState.ARMING, AlarmState.ARMED_HOME},
                )
                self.assertIn("effective_settings", payload)
            finally:
                await communicator.disconnect()

        asyncio.run(run())

    def test_websocket_state_update_sequence_is_monotonic(self):
        user = User.objects.create_user(email="wsseq@example.com", password="pass")
        token = Token.objects.create(user=user)

        @database_sync_to_async
        def arm_alarm():
            transitions.disarm(reason="test_setup")
            transitions.arm(target_state=AlarmState.ARMED_HOME, reason="test_arm")

        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={token.key}")
            try:
                connected, _ = await communicator.connect()
                self.assertTrue(connected)

                initial_one = await communicator.receive_json_from(timeout=1)
                initial_two = await communicator.receive_json_from(timeout=1)
                max_initial_sequence = max(
                    int(initial_one.get("sequence") or 0),
                    int(initial_two.get("sequence") or 0),
                )

                await arm_alarm()

                got_update = False
                for _ in range(4):
                    msg = await communicator.receive_json_from(timeout=1)
                    if msg.get("type") != "alarm_state":
                        continue
                    payload = msg.get("payload") or {}
                    state = payload.get("state") or {}
                    if state.get("current_state") in {AlarmState.ARMING, AlarmState.ARMED_HOME}:
                        got_update = True
                        self.assertGreater(int(msg.get("sequence") or 0), max_initial_sequence)
                        break

                self.assertTrue(got_update)
            finally:
                await communicator.disconnect()

        asyncio.run(run())

    def test_websocket_connect_tolerates_initial_system_status_errors(self):
        user = User.objects.create_user(email="ws-tolerant@example.com", password="pass")
        token = Token.objects.create(user=user)

        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={token.key}")
            try:
                connected, _ = await communicator.connect()
                self.assertTrue(connected)

                first = await communicator.receive_json_from(timeout=1)
                self.assertEqual(first.get("type"), "alarm_state")

                await communicator.send_json_to({"type": "ping"})
                pong = await communicator.receive_json_from(timeout=1)
                self.assertEqual(pong, {"type": "pong"})
            finally:
                await communicator.disconnect()

        with patch("alarm.consumers.get_current_system_status_message", side_effect=RuntimeError("boom")):
            asyncio.run(run())

    def test_websocket_alarm_state_handles_uuid_fields(self):
        user = User.objects.create_user(email="wsuuid@example.com", password="pass")
        token = Token.objects.create(user=user)

        @database_sync_to_async
        def arm_then_disarm_with_user():
            transitions.disarm(reason="test_setup")
            transitions.arm(user=user, target_state=AlarmState.ARMED_HOME, reason="test_arm_with_user")
            transitions.disarm(user=user, reason="test_disarm_with_user")

        async def run():
            communicator = WebsocketCommunicator(application, f"/ws/alarm/?token={token.key}")
            try:
                connected, _ = await communicator.connect()
                self.assertTrue(connected)
                await communicator.receive_json_from(timeout=1)  # initial state

                await arm_then_disarm_with_user()

                # Expect at least 2 alarm_state messages (arm, then disarm). Grab until disarmed.
                last_msg = None
                for _ in range(4):
                    last_msg = await communicator.receive_json_from(timeout=1)
                    if (
                        last_msg.get("type") == "alarm_state"
                        and (last_msg.get("payload") or {}).get("state", {}).get("current_state") == AlarmState.DISARMED
                    ):
                        break

                self.assertIsNotNone(last_msg)
                self.assertEqual(last_msg.get("type"), "alarm_state")
                payload = last_msg.get("payload") or {}
                state = payload.get("state") or {}
                self.assertEqual(state.get("current_state"), AlarmState.DISARMED)
                # UUID primary keys should serialize to strings (not crash the websocket).
                if state.get("last_transition_by") is not None:
                    self.assertIsInstance(state.get("last_transition_by"), str)
            finally:
                await communicator.disconnect()

        asyncio.run(run())

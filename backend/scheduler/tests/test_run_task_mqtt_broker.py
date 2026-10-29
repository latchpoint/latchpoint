"""`run_task`'s alarm state publish against a real paho client and a small fake broker on 127.0.0.1 (#173)."""

from __future__ import annotations

import socket
import threading
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from integrations_home_assistant.mqtt_alarm_entity import STATE_TOPIC
from transports_mqtt.manager import MqttConnectionManager

from alarm.gateways.mqtt import DefaultMqttGateway
from alarm.models import AlarmState
from alarm.state_machine import transitions
from alarm.tests.settings_test_utils import EncryptionTestMixin, set_profile_settings
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from scheduler import Every, register, registry

_CONNACK_ACCEPTED = b"\x20\x02\x00\x00"
_PINGRESP = b"\xd0\x00"


class _FakeBroker:
    """Accepts one MQTT 3.1.1 client and records its CONNECT, PUBLISH and DISCONNECT packets in order."""

    def __init__(self) -> None:
        self._server = socket.create_server(("127.0.0.1", 0))
        self._server.settimeout(10)
        self.port = self._server.getsockname()[1]
        self.packets: list[tuple] = []
        self.done = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.close()
        self._thread.join(timeout=5)

    def _serve(self) -> None:
        try:
            conn, _addr = self._server.accept()
        except OSError:
            self.done.set()
            return
        with conn:
            conn.settimeout(10)
            try:
                while self._handle_packet(conn):
                    pass
            except OSError:
                pass
        self.done.set()

    @staticmethod
    def _recv_exact(conn: socket.socket, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = conn.recv(size - len(data))
            if not chunk:
                raise ConnectionError("client closed the connection")
            data += chunk
        return data

    def _handle_packet(self, conn: socket.socket) -> bool:
        try:
            header = self._recv_exact(conn, 1)[0]
        except ConnectionError:
            self.packets.append(("CLOSED",))
            return False
        remaining, multiplier = 0, 1
        while True:
            byte = self._recv_exact(conn, 1)[0]
            remaining += (byte & 0x7F) * multiplier
            multiplier *= 128
            if not byte & 0x80:
                break
        body = self._recv_exact(conn, remaining) if remaining else b""

        packet_type = header >> 4
        if packet_type == 1:
            self.packets.append(("CONNECT",))
            conn.sendall(_CONNACK_ACCEPTED)
        elif packet_type == 3:
            qos = (header >> 1) & 0x03
            topic_len = int.from_bytes(body[:2], "big")
            topic = body[2 : 2 + topic_len].decode()
            payload_at = 2 + topic_len + (2 if qos else 0)
            self.packets.append(("PUBLISH", topic, body[payload_at:].decode(), bool(header & 0x01), qos))
        elif packet_type == 12:
            conn.sendall(_PINGRESP)
        elif packet_type == 14:
            self.packets.append(("DISCONNECT",))
            return False
        else:
            self.packets.append(("UNEXPECTED", packet_type))
        return True


class RunTaskRealMqttPublishTests(EncryptionTestMixin, TestCase):
    def setUp(self):
        registry_patch = patch.dict(registry._tasks, clear=True)
        registry_patch.start()
        self.addCleanup(registry_patch.stop)

        self.broker = _FakeBroker()
        self.addCleanup(self.broker.close)

        set_profile_settings(
            ensure_active_settings_profile(),
            arming_time=0,
            mqtt={"enabled": True, "host": "127.0.0.1", "port": self.broker.port, "connect_timeout_seconds": 5},
            home_assistant_alarm_entity={"enabled": True},
        )

        # A manager of its own, so no on-connect hooks or subscriptions other tests left on the shared one come along.
        manager = MqttConnectionManager()
        for target, value in (
            ("alarm.gateways.mqtt.default_mqtt_gateway", DefaultMqttGateway(manager=manager)),
            ("transports_mqtt.manager.mqtt_connection_manager", manager),
        ):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(manager.apply_settings, settings={"enabled": False})

    def test_the_retained_state_reaches_the_broker_before_the_disconnect(self):
        @register("process_alarm_timers_like", schedule=Every(seconds=60))
        def _task():
            with self.captureOnCommitCallbacks(execute=True):
                transitions.arm(target_state=AlarmState.ARMED_AWAY, reason="test")

        out, err = StringIO(), StringIO()
        call_command("run_task", "process_alarm_timers_like", stdout=out, stderr=err)

        self.assertTrue(self.broker.done.wait(timeout=10), self.broker.packets)
        self.assertEqual(
            self.broker.packets,
            [("CONNECT",), ("PUBLISH", STATE_TOPIC, AlarmState.ARMED_AWAY, True, 0), ("DISCONNECT",)],
            err.getvalue(),
        )
        self.assertIn("Published the alarm state (armed_away) to the Home Assistant alarm entity.", out.getvalue())

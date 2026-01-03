from __future__ import annotations

from django.test import SimpleTestCase

from transports_mqtt.manager import _format_connect_error
from transports_mqtt.manager import MqttConnectionManager


class MqttConnectErrorFormattingTests(SimpleTestCase):
    def test_formats_rc5_with_auth_hint_when_no_credentials(self):
        msg = _format_connect_error(rc_int=5, settings={"username": "", "password": ""})
        self.assertIn("Not authorized", msg)
        self.assertIn("provide a username/password", msg)

    def test_formats_rc4_with_acl_hint_when_credentials_present(self):
        msg = _format_connect_error(rc_int=4, settings={"username": "u", "password": "p"})
        self.assertIn("Bad username or password", msg)
        self.assertIn("Check username/password", msg)

    def test_formats_rc2_with_client_id_hint(self):
        msg = _format_connect_error(rc_int=2, settings={"client_id": "latchpoint-alarm"})
        self.assertIn("Identifier rejected", msg)
        self.assertIn("different client_id", msg)


class MqttSubscriptionDispatchTests(SimpleTestCase):
    def test_dispatches_to_wildcard_subscriptions(self):
        mgr = MqttConnectionManager()
        seen = []

        def cb(*, topic: str, payload: str):
            seen.append((topic, payload))

        mgr.subscribe(topic="zigbee2mqtt/+", qos=0, callback=cb)

        class _Msg:
            topic = "zigbee2mqtt/front_door"
            payload = b'{"contact":true}'

        mgr._on_message(None, None, _Msg())
        self.assertEqual(seen, [("zigbee2mqtt/front_door", '{"contact":true}')])

    def test_dispatches_to_multiple_callbacks_for_same_topic(self):
        mgr = MqttConnectionManager()
        calls = []

        def cb1(*, topic: str, payload: str):
            calls.append(("a", topic))

        def cb2(*, topic: str, payload: str):
            calls.append(("b", topic))

        mgr.subscribe(topic="t", qos=0, callback=cb1)
        mgr.subscribe(topic="t", qos=0, callback=cb2)

        class _Msg:
            topic = "t"
            payload = b"x"

        mgr._on_message(None, None, _Msg())
        self.assertEqual(calls, [("a", "t"), ("b", "t")])

    def test_unsubscribe_removes_callback(self):
        mgr = MqttConnectionManager()
        calls = []

        def cb(*, topic: str, payload: str):
            calls.append(topic)

        mgr.subscribe(topic="t", qos=0, callback=cb)

        class _Msg:
            topic = "t"
            payload = b"x"

        mgr._on_message(None, None, _Msg())
        mgr.unsubscribe(topic="t", callback=cb)
        mgr._on_message(None, None, _Msg())

        self.assertEqual(calls, ["t"])

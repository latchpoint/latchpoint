from __future__ import annotations

from django.test import SimpleTestCase

from transports_mqtt.manager import MqttConnectionManager, _format_connect_error


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


class _FakePahoModule:
    """Stand-in for `paho.mqtt.client` that captures the client_id paho would receive."""

    class Client:
        def __init__(self, client_id=None):
            self.client_id = client_id

        def username_pw_set(self, *_a, **_k):
            pass

        def tls_set(self, *_a, **_k):
            pass

        def tls_insecure_set(self, *_a, **_k):
            pass

        def reconnect_delay_set(self, *_a, **_k):
            pass


class MqttClientIdSuffixTests(SimpleTestCase):
    """
    Per-process suffix on the broker-side client_id.

    Without the suffix, two processes connecting with the configured
    `client_id` (default "latchpoint-alarm") would knock each other off the
    broker on every reconnect — including a diagnostic script that imported
    the Django app and ran AppConfig.ready() inside the live container.
    """

    def test_two_managers_produce_distinct_client_ids(self):
        a = MqttConnectionManager()
        b = MqttConnectionManager()
        client_a = a._build_client(mqtt=_FakePahoModule, settings={"client_id": "latchpoint-alarm"})
        client_b = b._build_client(mqtt=_FakePahoModule, settings={"client_id": "latchpoint-alarm"})
        self.assertNotEqual(client_a.client_id, client_b.client_id)

    def test_same_manager_produces_stable_client_id_across_rebuilds(self):
        """Reconnects within a process must not look like new identities to the broker."""
        mgr = MqttConnectionManager()
        first = mgr._build_client(mqtt=_FakePahoModule, settings={"client_id": "latchpoint-alarm"})
        second = mgr._build_client(mqtt=_FakePahoModule, settings={"client_id": "latchpoint-alarm"})
        self.assertEqual(first.client_id, second.client_id)

    def test_built_client_id_preserves_configured_prefix(self):
        mgr = MqttConnectionManager()
        client = mgr._build_client(mqtt=_FakePahoModule, settings={"client_id": "my-custom-id"})
        self.assertTrue(
            client.client_id.startswith("my-custom-id-"),
            f"expected prefix preserved, got {client.client_id!r}",
        )

    def test_empty_configured_client_id_falls_back_to_latchpoint_alarm_prefix(self):
        mgr = MqttConnectionManager()
        client = mgr._build_client(mqtt=_FakePahoModule, settings={})
        self.assertTrue(
            client.client_id.startswith("latchpoint-alarm-"),
            f"expected default prefix preserved, got {client.client_id!r}",
        )

    def test_explicit_suffix_override_does_not_collide_with_live_suffix(self):
        """`test_connection` opts into a fresh suffix so it never knocks the live client off."""
        mgr = MqttConnectionManager()
        live = mgr._build_client(mqtt=_FakePahoModule, settings={"client_id": "latchpoint-alarm"})
        test = mgr._build_client(
            mqtt=_FakePahoModule,
            settings={"client_id": "latchpoint-alarm"},
            client_id_suffix="abcd1234",
        )
        self.assertNotEqual(live.client_id, test.client_id)
        self.assertTrue(test.client_id.endswith("-abcd1234"))

    def test_typeerror_on_kwarg_falls_back_to_positional_with_suffix_intact(self):
        """
        Compat fallback: if a paho version ever rejects `client_id=` as a
        kwarg, the manager retries positionally. The composed
        `<prefix>-<suffix>` MUST still reach the broker — otherwise the
        per-process collision fix is silently lost.
        """
        captured: dict[str, object] = {}

        class _KwargRejectingPahoModule:
            class Client:
                def __init__(self, *args, **kwargs):
                    if "client_id" in kwargs:
                        raise TypeError("client_id keyword unsupported in this paho version")
                    captured["positional_args"] = args
                    self.client_id = args[0] if args else None

                def username_pw_set(self, *_a, **_k):
                    pass

                def tls_set(self, *_a, **_k):
                    pass

                def tls_insecure_set(self, *_a, **_k):
                    pass

                def reconnect_delay_set(self, *_a, **_k):
                    pass

        mgr = MqttConnectionManager()
        client = mgr._build_client(
            mqtt=_KwargRejectingPahoModule,
            settings={"client_id": "latchpoint-alarm"},
        )
        self.assertTrue(
            client.client_id.startswith("latchpoint-alarm-"),
            f"fallback dropped the prefix: {client.client_id!r}",
        )
        self.assertEqual(client.client_id, captured["positional_args"][0])

    def test_test_connection_passes_a_fresh_non_live_suffix_to_build_client(self):
        """
        Wiring guard: `test_connection()` MUST forward a non-None override
        suffix that differs from the manager's live persistent suffix. If this
        ever regresses, a `test_connection` invoked from inside the live
        container would reuse the live suffix and the broker would evict the
        running daphne client mid-validation.
        """
        mgr = MqttConnectionManager()
        captured: dict[str, object] = {}

        def fake_build_client(*, mqtt, settings, client_id_suffix=None):
            captured["client_id_suffix"] = client_id_suffix
            raise RuntimeError("short-circuit before connect_async")

        mgr._build_client = fake_build_client  # type: ignore[assignment]
        mgr._import_paho = lambda: _FakePahoModule  # type: ignore[assignment]

        with self.assertRaises(RuntimeError):
            mgr.test_connection(settings={"host": "broker.example", "port": 1883, "client_id": "latchpoint-alarm"})

        suffix = captured.get("client_id_suffix")
        self.assertIsNotNone(suffix, "test_connection must pass a non-None client_id_suffix to _build_client")
        self.assertNotEqual(
            suffix,
            mgr._client_id_suffix,
            "test_connection's per-call suffix must differ from the live manager suffix",
        )

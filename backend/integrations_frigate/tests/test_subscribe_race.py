"""Two threads subscribing at once register each Frigate handler once (#164)."""

from __future__ import annotations

import contextlib
import threading
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations_frigate import runtime


class _RacySet(set):
    """A set whose membership check waits for a second thread, so both pass it unless a lock serializes them."""

    def __init__(self) -> None:
        super().__init__()
        self.barrier = threading.Barrier(2, timeout=0.5)

    def __contains__(self, item) -> bool:
        # Read first, then wait for the other thread, so without a lock both get the answer from before either add.
        found = super().__contains__(item)
        with contextlib.suppress(threading.BrokenBarrierError):
            self.barrier.wait()
        return found


class _RecordingMqttManager:
    def __init__(self) -> None:
        self.subscribed: Counter[str] = Counter()
        self._lock = threading.Lock()

    def subscribe(self, *, topic: str, qos: int = 0, callback=None) -> None:
        with self._lock:
            self.subscribed[topic] += 1


class SubscribeRaceTests(SimpleTestCase):
    def test_each_topic_is_subscribed_once(self):
        fake = _RecordingMqttManager()
        settings = SimpleNamespace(events_topic="frigate/events")
        with (
            patch.object(runtime, "_subscribed_topics", _RacySet()),
            patch.object(runtime, "mqtt_connection_manager", fake),
        ):
            threads = [threading.Thread(target=runtime._subscribe, kwargs={"settings": settings}) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        self.assertEqual(dict(fake.subscribed), {"frigate/events": 1, "frigate/available": 1})

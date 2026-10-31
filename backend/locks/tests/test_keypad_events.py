"""Parsing keypad unlocks out of Z-Wave JS bridge events (issue #145)."""

from __future__ import annotations

import copy

from django.test import SimpleTestCase

from locks.keypad_events import KeypadUnlock, is_notification_cc_event, parse_keypad_unlock

# What the bridge hands its listeners for a Yale keypad unlock: zwave-js-server's
# node "notification" payload wrapped in {"event": ...}, with the library's
# model objects the manager's coercion keeps alongside.
REAL_PAYLOAD = {
    "event": {
        "source": "node",
        "event": "notification",
        "nodeId": 12,
        "endpointIndex": 0,
        "ccId": 113,
        "args": {
            "type": 6,
            "label": "Access Control",
            "event": 6,
            "eventLabel": "Keypad unlock operation",
            "parameters": {"userId": 3},
        },
        "node": object(),
        "notification": object(),
    }
}


def _payload(**changes) -> dict:
    msg = copy.deepcopy(
        {"event": {k: v for k, v in REAL_PAYLOAD["event"].items() if k not in ("node", "notification")}}
    )
    event = msg["event"]
    for key, value in changes.items():
        if key in ("type", "event_number", "parameters"):
            event["args"]["event" if key == "event_number" else key] = value
        else:
            event[key] = value
    return msg


class ParseKeypadUnlockTests(SimpleTestCase):
    def test_real_payload_shape_is_a_keypad_unlock(self):
        self.assertEqual(parse_keypad_unlock(REAL_PAYLOAD), KeypadUnlock(node_id=12, slot=3, event=6))

    def test_credential_unlock_event_34_counts(self):
        self.assertEqual(parse_keypad_unlock(_payload(event_number=34)), KeypadUnlock(node_id=12, slot=3, event=34))

    def test_keypad_lock_event_5_is_ignored(self):
        self.assertIsNone(parse_keypad_unlock(_payload(event_number=5)))

    def test_other_access_control_events_are_ignored(self):
        # 1/2 manual, 3/4 RF, 11 jammed.
        for number in (1, 2, 3, 4, 11):
            with self.subTest(event=number):
                self.assertIsNone(parse_keypad_unlock(_payload(event_number=number)))

    def test_other_notification_types_are_ignored(self):
        # Home Security (7) event 6 is something else entirely.
        self.assertIsNone(parse_keypad_unlock(_payload(type=7)))

    def test_entry_control_cc_111_is_ignored(self):
        msg = {
            "event": {
                "source": "node",
                "event": "notification",
                "nodeId": 12,
                "ccId": 111,
                "args": {"eventType": 6, "eventData": "1996", "type": 6, "event": 6, "parameters": {"userId": 3}},
            }
        }
        self.assertIsNone(parse_keypad_unlock(msg))
        self.assertFalse(is_notification_cc_event(msg))

    def test_no_parameters_is_ignored(self):
        msg = _payload()
        del msg["event"]["args"]["parameters"]
        self.assertIsNone(parse_keypad_unlock(msg))
        self.assertIsNone(parse_keypad_unlock(_payload(parameters=None)))
        self.assertIsNone(parse_keypad_unlock(_payload(parameters={})))

    def test_raw_buffer_parameters_are_ignored(self):
        self.assertIsNone(parse_keypad_unlock(_payload(parameters={"type": "Buffer", "data": [3]})))
        self.assertIsNone(parse_keypad_unlock(_payload(parameters=3)))

    def test_user_id_zero_or_not_an_int_is_ignored(self):
        for user_id in (0, -1, "3", 3.0, True, None):
            with self.subTest(user_id=user_id):
                self.assertIsNone(parse_keypad_unlock(_payload(parameters={"userId": user_id})))

    def test_missing_node_id_is_ignored(self):
        self.assertIsNone(parse_keypad_unlock(_payload(nodeId=None)))

    def test_value_events_for_cc_113_are_ignored(self):
        msg = {
            "event": {
                "source": "node",
                "event": "value notification",
                "nodeId": 12,
                "ccId": 113,
                "args": {"type": 6, "event": 6, "parameters": {"userId": 3}},
            }
        }
        self.assertIsNone(parse_keypad_unlock(msg))

    def test_not_an_envelope_is_ignored(self):
        for msg in (None, "x", {}, {"event": "notification"}, REAL_PAYLOAD["event"]):
            with self.subTest(msg=type(msg).__name__):
                self.assertIsNone(parse_keypad_unlock(msg))

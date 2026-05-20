from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from control_panels.models import (
    ControlPanelDevice,
    ControlPanelIntegrationType,
    ControlPanelKind,
)
from control_panels.services import (
    ControlPanelNotFound,
    apply_panel_state,
    resume_auto,
    resume_auto_all_on_disarm,
    trigger_panel,
)


def _make_device(*, follow_alarm_state: bool = True, enabled: bool = True, suffix: str = "1") -> ControlPanelDevice:
    return ControlPanelDevice.objects.create(
        name=f"Ring-{suffix}",
        integration_type=ControlPanelIntegrationType.ZWAVEJS,
        kind=ControlPanelKind.RING_KEYPAD_V2,
        enabled=enabled,
        external_key=f"zwavejs:4170970308:{suffix}",
        external_id={"home_id": 4170970308, "node_id": int(suffix)},
        beep_volume=50,
        action_map={
            "disarm": "disarmed",
            "arm_home": "armed_home",
            "arm_away": "armed_away",
            "cancel": "cancel_arming",
        },
        follow_alarm_state=follow_alarm_state,
    )


class ApplyPanelStateTests(TestCase):
    def test_flips_follow_alarm_state_false_and_dispatches_write(self):
        device = _make_device()
        with (
            patch("control_panels.zwave_ring_keypad_v2.apply_ring_keypad_v2_panel_state") as apply_mock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = apply_panel_state(panel_id=device.id, state="armed_away", countdown_seconds=15)

        self.assertEqual(result.id, device.id)
        device.refresh_from_db()
        self.assertFalse(device.follow_alarm_state)
        apply_mock.assert_called_once()
        kwargs = apply_mock.call_args.kwargs
        self.assertEqual(kwargs["state"], "armed_away")
        self.assertEqual(kwargs["countdown_seconds"], 15)
        self.assertEqual(kwargs["device"].id, device.id)

    def test_idempotent_when_already_false(self):
        device = _make_device(follow_alarm_state=False)
        with (
            patch("control_panels.zwave_ring_keypad_v2.apply_ring_keypad_v2_panel_state") as apply_mock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            apply_panel_state(panel_id=device.id, state="triggered")

        device.refresh_from_db()
        self.assertFalse(device.follow_alarm_state)
        apply_mock.assert_called_once()

    def test_raises_control_panel_not_found_for_missing_id(self):
        with self.assertRaises(ControlPanelNotFound):
            apply_panel_state(panel_id=999_999, state="armed_away")

    def test_raises_control_panel_not_found_for_disabled_panel(self):
        device = _make_device(enabled=False)
        with self.assertRaises(ControlPanelNotFound):
            apply_panel_state(panel_id=device.id, state="armed_away")

    def test_swallows_keypad_write_exception(self):
        device = _make_device()
        with (
            patch(
                "control_panels.zwave_ring_keypad_v2.apply_ring_keypad_v2_panel_state",
                side_effect=RuntimeError("zwavejs offline"),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            apply_panel_state(panel_id=device.id, state="armed_away")

        device.refresh_from_db()
        self.assertFalse(device.follow_alarm_state)

    def test_skips_dispatch_when_integration_type_unsupported(self):
        device = _make_device()
        ControlPanelDevice.objects.filter(id=device.id).update(
            integration_type=ControlPanelIntegrationType.HOME_ASSISTANT,
        )
        with (
            patch("control_panels.zwave_ring_keypad_v2.apply_ring_keypad_v2_panel_state") as apply_mock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            apply_panel_state(panel_id=device.id, state="armed_away")

        apply_mock.assert_not_called()


class TriggerPanelTests(TestCase):
    def test_delegates_to_apply_panel_state_with_triggered(self):
        device = _make_device()
        with (
            patch("control_panels.zwave_ring_keypad_v2.apply_ring_keypad_v2_panel_state") as apply_mock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            trigger_panel(panel_id=device.id)

        device.refresh_from_db()
        self.assertFalse(device.follow_alarm_state)
        apply_mock.assert_called_once()
        self.assertEqual(apply_mock.call_args.kwargs["state"], "triggered")
        self.assertIsNone(apply_mock.call_args.kwargs["countdown_seconds"])

    def test_raises_when_panel_missing(self):
        with self.assertRaises(ControlPanelNotFound):
            trigger_panel(panel_id=999_999)


class ResumeAutoTests(TestCase):
    def test_flips_follow_alarm_state_true_and_syncs(self):
        device = _make_device(follow_alarm_state=False)
        with (
            patch("control_panels.zwave_ring_keypad_v2.sync_ring_keypad_v2_devices_state") as sync_mock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            resume_auto(panel_id=device.id)

        device.refresh_from_db()
        self.assertTrue(device.follow_alarm_state)
        sync_mock.assert_called_once()

    def test_idempotent_when_already_true(self):
        device = _make_device(follow_alarm_state=True)
        with (
            patch("control_panels.zwave_ring_keypad_v2.sync_ring_keypad_v2_devices_state") as sync_mock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            resume_auto(panel_id=device.id)

        device.refresh_from_db()
        self.assertTrue(device.follow_alarm_state)
        sync_mock.assert_called_once()

    def test_raises_when_panel_missing(self):
        with self.assertRaises(ControlPanelNotFound):
            resume_auto(panel_id=999_999)

    def test_swallows_sync_exception(self):
        device = _make_device(follow_alarm_state=False)
        with (
            patch(
                "control_panels.zwave_ring_keypad_v2.sync_ring_keypad_v2_devices_state",
                side_effect=RuntimeError("zwavejs offline"),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            resume_auto(panel_id=device.id)

        device.refresh_from_db()
        self.assertTrue(device.follow_alarm_state)


class ResumeAutoAllOnDisarmTests(TestCase):
    def test_flips_all_panels_with_follow_alarm_state_false_to_true(self):
        d1 = _make_device(follow_alarm_state=False, suffix="1")
        d2 = _make_device(follow_alarm_state=False, suffix="2")
        d3 = _make_device(follow_alarm_state=True, suffix="3")

        count = resume_auto_all_on_disarm()

        self.assertEqual(count, 2)
        d1.refresh_from_db()
        d2.refresh_from_db()
        d3.refresh_from_db()
        self.assertTrue(d1.follow_alarm_state)
        self.assertTrue(d2.follow_alarm_state)
        self.assertTrue(d3.follow_alarm_state)

    def test_returns_zero_when_no_rule_controlled_panels(self):
        _make_device(follow_alarm_state=True, suffix="1")
        self.assertEqual(resume_auto_all_on_disarm(), 0)

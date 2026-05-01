from __future__ import annotations

import json

from django.test import SimpleTestCase

from integrations_home_assistant.mqtt_alarm_entity import build_discovery_payload


class BuildDiscoveryPayloadTests(SimpleTestCase):
    """Unit tests for the HA MQTT alarm_control_panel discovery payload builder."""

    def _payload(self, *, entity_name: str = "Latchpoint", code_arm_required: bool = False) -> dict:
        return build_discovery_payload(entity_name=entity_name, code_arm_required=code_arm_required)

    def test_code_is_remote_code_sentinel(self):
        """`code: REMOTE_CODE` is what makes HA expose a numeric keypad while skipping local validation."""
        payload = self._payload()
        self.assertEqual(payload["code"], "REMOTE_CODE")

    def test_supported_features_only_lists_implemented_modes(self):
        """HA's default supported_features adds arm_custom_bypass and trigger; Latchpoint implements neither."""
        payload = self._payload()
        self.assertEqual(
            payload["supported_features"],
            ["arm_home", "arm_away", "arm_night", "arm_vacation"],
        )

    def test_code_disarm_required_is_always_true(self):
        for code_arm_required in (True, False):
            with self.subTest(code_arm_required=code_arm_required):
                payload = self._payload(code_arm_required=code_arm_required)
                self.assertIs(payload["code_disarm_required"], True)

    def test_code_arm_required_round_trips_parameter(self):
        self.assertIs(self._payload(code_arm_required=True)["code_arm_required"], True)
        self.assertIs(self._payload(code_arm_required=False)["code_arm_required"], False)

    def test_command_template_uses_ha_documented_action_and_code_variables(self):
        """
        Regression guard: HA's `alarm_control_panel.mqtt` exposes only `action`
        and `code` to `command_template` (NOT `value`, which is `lock.mqtt`'s
        scope). Rendering `{{ value }}` would emit the literal "None" and the
        action would fail to dispatch. See:
        https://www.home-assistant.io/integrations/alarm_control_panel.mqtt/#command_template
        """
        payload = self._payload()
        template = payload["command_template"]
        parsed = json.loads(template)
        self.assertEqual(parsed, {"action": "{{ action }}", "code": "{{ code }}"})

    def test_entity_name_is_passed_through(self):
        payload = self._payload(entity_name="Front Door Alarm")
        self.assertEqual(payload["name"], "Front Door Alarm")

    def test_arm_payloads_match_action_keys(self):
        """The payload_arm_* values must match the keys consumed by `_ACTION_TO_STATE`."""
        payload = self._payload()
        self.assertEqual(payload["payload_disarm"], "DISARM")
        self.assertEqual(payload["payload_arm_home"], "ARM_HOME")
        self.assertEqual(payload["payload_arm_away"], "ARM_AWAY")
        self.assertEqual(payload["payload_arm_night"], "ARM_NIGHT")
        self.assertEqual(payload["payload_arm_vacation"], "ARM_VACATION")

    def test_rendered_command_payload_has_real_action_not_literal_none(self):
        """
        Simulated render check against HA's documented variable scope.

        Captures the empirical failure mode that motivated this test class:
        when the template referenced `{{ value }}` (undefined for
        `alarm_control_panel.mqtt`), Jinja rendered it as the literal string
        "None" and the broker payload looked like
        `{"action": "None", "code": "1996"}`, which `_ACTION_TO_STATE` then
        rejected as "Unknown action.".

        Uses Django's template engine (always available) as a stand-in for
        Jinja2; both substitute `{{ var }}` identically when the variables
        are defined.
        """
        from django.template import Context, Template

        payload = self._payload()
        rendered = Template(payload["command_template"]).render(Context({"action": "ARM_AWAY", "code": "1234"}))
        parsed = json.loads(rendered)
        self.assertEqual(parsed, {"action": "ARM_AWAY", "code": "1234"})

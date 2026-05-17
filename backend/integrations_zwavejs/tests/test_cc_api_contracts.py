"""Direct unit tests for the CC API arg-shape contracts."""

from __future__ import annotations

from django.test import SimpleTestCase

from integrations_zwavejs.cc_api_contracts import (
    CcApiContractViolation,
    validate_cc_api_args,
)


class CcApiContractsTests(SimpleTestCase):
    def test_cc_99_set_accepts_three_args_with_correct_types(self):
        # (userId, userIdStatus, userCode) — the shape we proved against the real ZJS server.
        validate_cc_api_args(command_class=99, method_name="set", args=[3, 1, "1234"])

    def test_cc_99_set_rejects_two_arg_call(self):
        # The bug that bit prod: 2 args, PIN landing where userIdStatus is expected.
        with self.assertRaises(CcApiContractViolation) as ctx:
            validate_cc_api_args(command_class=99, method_name="set", args=[3, "1234"])
        self.assertIn("expected 3 args", str(ctx.exception))

    def test_cc_99_set_rejects_wrong_userIdStatus_type(self):
        with self.assertRaises(CcApiContractViolation) as ctx:
            validate_cc_api_args(command_class=99, method_name="set", args=[3, "1", "1234"])
        self.assertIn("userIdStatus", str(ctx.exception))

    def test_cc_99_set_rejects_non_string_userCode(self):
        with self.assertRaises(CcApiContractViolation) as ctx:
            validate_cc_api_args(command_class=99, method_name="set", args=[3, 1, 1234])
        self.assertIn("userCode", str(ctx.exception))

    def test_cc_99_set_rejects_bool_in_int_slot(self):
        # bool is a subclass of int in Python; the predicate must exclude it.
        with self.assertRaises(CcApiContractViolation):
            validate_cc_api_args(command_class=99, method_name="set", args=[True, 1, "1234"])

    def test_cc_99_clear_takes_one_int(self):
        validate_cc_api_args(command_class=99, method_name="clear", args=[5])

    def test_cc_99_clear_rejects_zero_args(self):
        with self.assertRaises(CcApiContractViolation):
            validate_cc_api_args(command_class=99, method_name="clear", args=[])

    def test_cc_78_daily_schedule_takes_one_dict(self):
        validate_cc_api_args(
            command_class=78,
            method_name="setDailyRepeatingSchedule",
            args=[{"userId": 1, "slotId": 1}],
        )

    def test_cc_78_daily_schedule_rejects_list(self):
        with self.assertRaises(CcApiContractViolation):
            validate_cc_api_args(command_class=78, method_name="setDailyRepeatingSchedule", args=[["not", "a", "dict"]])

    def test_unknown_cc_method_combo_passes_unvalidated(self):
        # We don't want to break things we haven't characterised; only enforce
        # the entries explicitly added to the contract table.
        validate_cc_api_args(command_class=99, method_name="get", args=["anything"])
        validate_cc_api_args(command_class=999, method_name="something_made_up", args=[1, 2, 3])

    def test_none_args_treated_as_empty(self):
        with self.assertRaises(CcApiContractViolation):
            validate_cc_api_args(command_class=99, method_name="set", args=None)

"""ADR-0088 AC-13: assert frontend template-variable list matches the backend.

The renderer's allow-list (``backend/alarm/rules/template_render.py``) and the
frontend chip + reference list (``frontend/src/features/rules/templateVariables.ts``)
must advertise the same set of tokens. This test parses the TypeScript source
file at test time and diffs its ``token: '...'`` values against the canonical
expected set defined here.

Adding a new token requires updating both sides AND this test, which is the
behaviour AC-13 asks for: the test fails loudly if either side drifts.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

# Canonical list of tokens advertised to users. Must match every entry in
# ``TEMPLATE_VARIABLES`` in ``frontend/src/features/rules/templateVariables.ts``.
# The renderer additionally accepts the bare forms ``{{trigger}}``, ``{{rule}}``
# (resolving to the friendly name / rule name) — those are intentionally NOT
# advertised in the chip picker since they are syntactic sugar for ``.name``.
EXPECTED_FRONTEND_TOKENS: frozenset[str] = frozenset(
    {
        "{{trigger.name}}",
        "{{trigger.entity_id}}",
        "{{trigger.state}}",
        "{{trigger.source}}",
        "{{trigger.domain}}",
        "{{trigger.attributes.battery}}",
        "{{triggers}}",
        "{{rule.name}}",
        "{{rule.kind}}",
        "{{now}}",
        "{{now.iso}}",
    }
)

# Path resolution: tests run inside the backend container which mounts the
# repo root at /app, so ``parents[3]`` from this file lands at the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FE_TEMPLATE_VARIABLES = _REPO_ROOT / "frontend/src/features/rules/templateVariables.ts"

# Backref ensures the closing quote matches the opener (no `"foo'` cross-pairs).
# Tolerant of single quotes, double quotes, and backticks so a Prettier reformat
# does not falsely trip the drift check.
_TOKEN_RE = re.compile(r"token:\s*(['\"`])(.+?)\1")


class TemplateVariableDriftTests(SimpleTestCase):
    """AC-13: keep frontend ``TEMPLATE_VARIABLES`` and backend renderer in sync."""

    def test_frontend_advertises_exactly_the_expected_token_set(self):
        """Every token in ``templateVariables.ts`` must be in the expected set, and vice versa."""
        self.assertTrue(
            _FE_TEMPLATE_VARIABLES.exists(),
            f"frontend template-variables file not reachable at {_FE_TEMPLATE_VARIABLES}",
        )
        text = _FE_TEMPLATE_VARIABLES.read_text(encoding="utf-8")
        # Group 1 is the quote char (used by the backref); group 2 is the token.
        found = {m.group(2) for m in _TOKEN_RE.finditer(text)}
        missing = EXPECTED_FRONTEND_TOKENS - found
        extra = found - EXPECTED_FRONTEND_TOKENS
        self.assertEqual(
            missing,
            set(),
            f"frontend templateVariables.ts is missing advertised tokens: {sorted(missing)}",
        )
        self.assertEqual(
            extra,
            set(),
            f"frontend templateVariables.ts advertises tokens not in the expected set: {sorted(extra)}",
        )

    def test_renderer_resolves_every_advertised_token(self):
        """Every advertised token must resolve to non-literal output against a populated context."""
        from datetime import datetime
        from datetime import timezone as dt_timezone

        from alarm.models import Entity, Rule
        from alarm.rules.template_render import TriggerContext, render

        ent = Entity(
            entity_id="binary_sensor.back_door",
            name="Back Door",
            domain="binary_sensor",
            last_state="on",
            source="home_assistant",
            attributes={"battery": 87},
        )
        rule = Rule(name="Door Watch", kind="trigger", definition={})
        ctx = TriggerContext(
            fired_at=datetime(2026, 4, 30, 14, 32, 11, tzinfo=dt_timezone.utc),
            fire_source="immediate",
            trigger=ent,
            triggers=[ent],
        )
        # ``trigger.attributes.<key>`` is a documentation placeholder (``<key>``
        # is replaced by the user) — substitute a concrete attribute for the
        # round-trip resolution check.
        for token in EXPECTED_FRONTEND_TOKENS:
            concrete = token.replace("<key>", "battery")
            out = render(concrete, rule=rule, triggers=ctx)
            self.assertNotEqual(
                out,
                concrete,
                f"renderer did not resolve advertised token {concrete!r} — "
                "drift between frontend list and backend resolver",
            )

"""Tests for ``alarm.rules.template_render`` (ADR-0088).

Covers each variable, missing-path passthrough, hostile inputs, idempotency,
and the legacy literal-passthrough corpus that protects pre-existing rule
messages from being mangled.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_timezone

from django.test import SimpleTestCase
from django.utils import timezone

from alarm.models import Entity, Rule
from alarm.rules.template_render import TriggerContext, render


def _entity(
    *,
    entity_id: str = "binary_sensor.back_door",
    name: str = "Back Door",
    domain: str = "binary_sensor",
    last_state: str | None = "on",
    source: str = "home_assistant",
    attributes: dict | None = None,
) -> Entity:
    """Build an unsaved Entity instance for renderer tests."""
    return Entity(
        entity_id=entity_id,
        name=name,
        domain=domain,
        last_state=last_state,
        source=source,
        attributes=attributes if attributes is not None else {},
    )


def _rule(name: str = "Front Door Alarm", kind: str = "trigger") -> Rule:
    """Build an unsaved Rule instance for renderer tests."""
    return Rule(name=name, kind=kind, definition={})


def _ctx(
    *,
    trigger: Entity | None = None,
    triggers: list[Entity] | None = None,
    fired_at: datetime | None = None,
    fire_source: str = "immediate",
) -> TriggerContext:
    """Build a TriggerContext with sane defaults."""
    return TriggerContext(
        fired_at=fired_at or timezone.now(),
        fire_source=fire_source,
        trigger=trigger,
        triggers=triggers if triggers is not None else ([trigger] if trigger else []),
    )


class TriggerVariableTests(SimpleTestCase):
    """Variable-by-variable resolution under ``{{trigger.*}}``."""

    def test_trigger_entity_id(self):
        """Resolves ``{{trigger.entity_id}}`` to the entity's stable id."""
        out = render("ID: {{trigger.entity_id}}", rule=_rule(), triggers=_ctx(trigger=_entity()))
        self.assertEqual(out, "ID: binary_sensor.back_door")

    def test_trigger_name(self):
        """Resolves ``{{trigger.name}}`` to the friendly name."""
        out = render("By {{trigger.name}}", rule=_rule(), triggers=_ctx(trigger=_entity()))
        self.assertEqual(out, "By Back Door")

    def test_trigger_state(self):
        """Resolves ``{{trigger.state}}`` to the last_state string."""
        out = render("State {{trigger.state}}", rule=_rule(), triggers=_ctx(trigger=_entity(last_state="open")))
        self.assertEqual(out, "State open")

    def test_trigger_state_none_renders_empty(self):
        """``{{trigger.state}}`` becomes empty string when last_state is None."""
        out = render("[{{trigger.state}}]", rule=_rule(), triggers=_ctx(trigger=_entity(last_state=None)))
        self.assertEqual(out, "[]")

    def test_trigger_source(self):
        """Resolves ``{{trigger.source}}`` to the integration name."""
        out = render(
            "src={{trigger.source}}",
            rule=_rule(),
            triggers=_ctx(trigger=_entity(source="zwavejs")),
        )
        self.assertEqual(out, "src=zwavejs")

    def test_trigger_domain(self):
        """Resolves ``{{trigger.domain}}`` to the entity's domain."""
        out = render("d={{trigger.domain}}", rule=_rule(), triggers=_ctx(trigger=_entity(domain="light")))
        self.assertEqual(out, "d=light")

    def test_trigger_attributes_lookup(self):
        """Resolves ``{{trigger.attributes.<key>}}`` from the JSON dict."""
        ent = _entity(attributes={"battery": 87, "device_class": "door"})
        out = render(
            "battery={{trigger.attributes.battery}} class={{trigger.attributes.device_class}}",
            rule=_rule(),
            triggers=_ctx(trigger=ent),
        )
        self.assertEqual(out, "battery=87 class=door")

    def test_trigger_attributes_missing_passes_through(self):
        """Missing attribute keys ship as the literal ``{{...}}`` placeholder."""
        ent = _entity(attributes={"battery": 87})
        out = render("{{trigger.attributes.nonexistent}}", rule=_rule(), triggers=_ctx(trigger=ent))
        self.assertEqual(out, "{{trigger.attributes.nonexistent}}")

    def test_trigger_attributes_nested_dict_traversal(self):
        """Nested attribute dicts walk dotted paths (HA emits nested payloads)."""
        ent = _entity(attributes={"location": {"floor": "2", "room": "office"}})
        out = render(
            "{{trigger.attributes.location.room}}/{{trigger.attributes.location.floor}}",
            rule=_rule(),
            triggers=_ctx(trigger=ent),
        )
        self.assertEqual(out, "office/2")

    def test_trigger_attributes_nested_missing_passes_through(self):
        """Missing leaf inside a nested attribute dict passes through literally."""
        ent = _entity(attributes={"location": {"floor": "2"}})
        out = render("{{trigger.attributes.location.room}}", rule=_rule(), triggers=_ctx(trigger=ent))
        self.assertEqual(out, "{{trigger.attributes.location.room}}")

    def test_bare_trigger_uses_friendly_name(self):
        """Bare ``{{trigger}}`` resolves to the friendly name."""
        out = render("By {{trigger}}", rule=_rule(), triggers=_ctx(trigger=_entity()))
        self.assertEqual(out, "By Back Door")

    def test_trigger_none_passes_through(self):
        """Time-only / alarm-state-only rules see literal ``{{trigger.*}}`` text."""
        out = render(
            "By {{trigger.name}} ({{trigger.entity_id}})",
            rule=_rule(),
            triggers=_ctx(trigger=None, triggers=[]),
        )
        self.assertEqual(out, "By {{trigger.name}} ({{trigger.entity_id}})")


class TriggersListTests(SimpleTestCase):
    """Bare ``{{triggers}}`` joins matched-entity friendly names."""

    def test_single_entity(self):
        """A single matched entity renders as just its name."""
        ent = _entity(name="Back Door")
        out = render("{{triggers}}", rule=_rule(), triggers=_ctx(trigger=ent, triggers=[ent]))
        self.assertEqual(out, "Back Door")

    def test_multiple_entities_comma_joined(self):
        """Multiple entities are comma-joined in the order they were given."""
        a = _entity(entity_id="binary_sensor.back_door", name="Back Door")
        b = _entity(entity_id="binary_sensor.front_door", name="Front Door")
        out = render("Doors: {{triggers}}", rule=_rule(), triggers=_ctx(trigger=a, triggers=[a, b]))
        self.assertEqual(out, "Doors: Back Door, Front Door")

    def test_empty_list_renders_empty_string(self):
        """An empty triggers list renders as the empty string (not literal)."""
        out = render("[{{triggers}}]", rule=_rule(), triggers=_ctx(trigger=None, triggers=[]))
        self.assertEqual(out, "[]")


class RuleVariableTests(SimpleTestCase):
    """Resolution under ``{{rule.*}}``."""

    def test_rule_name(self):
        """Resolves ``{{rule.name}}`` to the firing rule's name."""
        out = render("Rule: {{rule.name}}", rule=_rule(name="Door Watch"), triggers=_ctx())
        self.assertEqual(out, "Rule: Door Watch")

    def test_rule_kind(self):
        """Resolves ``{{rule.kind}}`` to the rule's kind enum value."""
        out = render("k={{rule.kind}}", rule=_rule(kind="arm"), triggers=_ctx())
        self.assertEqual(out, "k=arm")

    def test_rule_unknown_field_passes_through(self):
        """Unknown ``{{rule.*}}`` paths render literally (no attribute walk)."""
        out = render("{{rule.id}}", rule=_rule(), triggers=_ctx())
        self.assertEqual(out, "{{rule.id}}")

    def test_bare_rule_uses_name(self):
        """Bare ``{{rule}}`` resolves to the rule name (mirrors ``{{trigger}}``)."""
        out = render("Rule: {{rule}}", rule=_rule(name="Door Watch"), triggers=_ctx())
        self.assertEqual(out, "Rule: Door Watch")


class NowVariableTests(SimpleTestCase):
    """Resolution of ``{{now}}`` and ``{{now.iso}}``."""

    def test_now_local_format(self):
        """Bare ``{{now}}`` uses local-time ``YYYY-MM-DD HH:MM:SS`` format."""
        fired = datetime(2026, 4, 30, 14, 32, 11, tzinfo=dt_timezone.utc)
        out = render("at {{now}}", rule=_rule(), triggers=_ctx(fired_at=fired))
        # Format depends on TZ; just assert shape and date components are present.
        self.assertRegex(out, r"^at \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_now_iso(self):
        """``{{now.iso}}`` renders the ISO-8601 representation."""
        fired = datetime(2026, 4, 30, 14, 32, 11, tzinfo=dt_timezone.utc)
        out = render("ts={{now.iso}}", rule=_rule(), triggers=_ctx(fired_at=fired))
        self.assertEqual(out, "ts=2026-04-30T14:32:11+00:00")


class HostileInputTests(SimpleTestCase):
    """Path-traversal and engine-internals attacks must render literally."""

    def test_dunder_class_passes_through(self):
        """``{{__class__}}`` is rejected at the leading-underscore guard."""
        out = render("{{__class__}}", rule=_rule(), triggers=_ctx(trigger=_entity()))
        self.assertEqual(out, "{{__class__}}")

    def test_trigger_dunder_init_passes_through(self):
        """Underscore-prefixed segments anywhere in a path are rejected."""
        out = render("{{trigger.__init__}}", rule=_rule(), triggers=_ctx(trigger=_entity()))
        self.assertEqual(out, "{{trigger.__init__}}")

    def test_rule_meta_passes_through(self):
        """Single-leading-underscore segments are rejected."""
        out = render("{{rule._meta}}", rule=_rule(), triggers=_ctx())
        self.assertEqual(out, "{{rule._meta}}")

    def test_attributes_underscore_key_passes_through(self):
        """Even attributes lookups reject underscore-prefixed keys."""
        ent = _entity(attributes={"_private": "secret", "battery": 50})
        out = render("{{trigger.attributes._private}}", rule=_rule(), triggers=_ctx(trigger=ent))
        self.assertEqual(out, "{{trigger.attributes._private}}")

    def test_unknown_root_passes_through(self):
        """Unknown roots like ``{{user.name}}`` render literally."""
        out = render("Hi {{user.name}}", rule=_rule(), triggers=_ctx(trigger=_entity()))
        self.assertEqual(out, "Hi {{user.name}}")

    def test_empty_braces_pass_through(self):
        """``{{}}`` does not match the grammar; ships verbatim."""
        out = render("raw {{}}", rule=_rule(), triggers=_ctx())
        self.assertEqual(out, "raw {{}}")

    def test_whitespace_only_braces_pass_through(self):
        """``{{ }}`` does not match either."""
        out = render("see {{ }}", rule=_rule(), triggers=_ctx())
        self.assertEqual(out, "see {{ }}")


class SinglePassRenderingTests(SimpleTestCase):
    """Security property: within ONE render call, resolved values are not re-scanned."""

    def test_attribute_value_containing_template_is_not_expanded(self):
        """An attribute whose value is literal ``{{rule.name}}`` is NOT re-rendered.

        Single-pass rendering is the property that prevents attacker-controlled
        entity attribute values from being interpreted as templates. The
        regex substitution function returns its result; that result is not
        re-scanned for further matches.
        """
        ent = _entity(attributes={"label": "{{rule.name}}"})
        ctx = _ctx(trigger=ent)
        rule = _rule(name="Door Watch")
        out = render("{{trigger.attributes.label}}", rule=rule, triggers=ctx)
        # The attribute value is ``{{rule.name}}`` — must ship literally, not
        # expand to ``Door Watch``.
        self.assertEqual(out, "{{rule.name}}")

    def test_fully_resolved_output_is_stable_under_second_render(self):
        """A render output containing no remaining tokens survives re-rendering."""
        ent = _entity()
        ctx = _ctx(trigger=ent)
        rule = _rule(name="X")
        once = render("Hi {{trigger.name}}", rule=rule, triggers=ctx)
        twice = render(once, rule=rule, triggers=ctx)
        self.assertEqual(once, "Hi Back Door")
        self.assertEqual(twice, once)


class LegacyPassthroughTests(SimpleTestCase):
    """Pre-existing literal content must not be reinterpreted as templates."""

    def test_single_brace_text(self):
        """``{var}`` (single brace) is not a template; ships verbatim."""
        out = render("hello {var}", rule=_rule(), triggers=_ctx())
        self.assertEqual(out, "hello {var}")

    def test_no_braces_at_all(self):
        """Plain text round-trips byte-identically."""
        out = render("Alarm triggered.", rule=_rule(), triggers=_ctx())
        self.assertEqual(out, "Alarm triggered.")

    def test_empty_string(self):
        """Empty input is empty output."""
        out = render("", rule=_rule(), triggers=_ctx())
        self.assertEqual(out, "")

    def test_none_input(self):
        """``None`` input renders as the empty string."""
        out = render(None, rule=_rule(), triggers=_ctx())
        self.assertEqual(out, "")

    def test_braced_typo_passes_through(self):
        """Typo'd variable name renders literally for self-evident debugging."""
        out = render("By {{trigger.nme}}", rule=_rule(), triggers=_ctx(trigger=_entity()))
        self.assertEqual(out, "By {{trigger.nme}}")


class WhitespaceAndMixedTests(SimpleTestCase):
    """Grammar tolerates inner whitespace; mixed templates resolve independently."""

    def test_inner_whitespace_tolerated(self):
        """``{{ trigger.name }}`` (with spaces) resolves the same as no spaces."""
        out = render("{{ trigger.name }}", rule=_rule(), triggers=_ctx(trigger=_entity()))
        self.assertEqual(out, "Back Door")

    def test_multiple_tokens_in_one_string(self):
        """Multiple placeholders in the same string each resolve independently."""
        ent = _entity()
        out = render(
            "{{trigger.name}} ({{trigger.entity_id}}) — {{rule.name}}",
            rule=_rule(name="Door Watch"),
            triggers=_ctx(trigger=ent),
        )
        self.assertEqual(out, "Back Door (binary_sensor.back_door) — Door Watch")

    def test_mixed_resolved_and_unresolved(self):
        """Resolved tokens render; unresolved tokens pass through; both in one string."""
        out = render(
            "{{trigger.name}} / {{user.name}}",
            rule=_rule(),
            triggers=_ctx(trigger=_entity()),
        )
        self.assertEqual(out, "Back Door / {{user.name}}")

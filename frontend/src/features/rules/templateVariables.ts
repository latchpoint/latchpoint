/**
 * Template variables available in rule notification action `message` and `title`
 * fields (ADR-0088).
 *
 * The token list MUST stay in sync with the backend allow-list in
 * `backend/alarm/rules/template_render.py` (`_ALLOWED_ROOTS` plus the
 * resolver methods in each `_Trigger` / `_Triggers` / `_Rule` / `_Now` class).
 */

export interface TemplateVariable {
  /** The token as it appears in templates, e.g. `{{trigger.name}}`. */
  token: string
  /** Short human label for the chip / table row. */
  label: string
  /** One-line description shown in the help tooltip. */
  description: string
  /** Concrete sample value rendered in the help tooltip. */
  example: string
}

/** Variables surfaced as click-to-insert chips beneath the input field. */
export const TEMPLATE_VARIABLE_CHIPS: TemplateVariable[] = [
  {
    token: '{{trigger.name}}',
    label: 'trigger.name',
    description: 'Friendly name of the entity that fired the rule',
    example: 'Back Door',
  },
  {
    token: '{{trigger.entity_id}}',
    label: 'trigger.entity_id',
    description: 'Stable entity ID of the firing entity',
    example: 'binary_sensor.back_door',
  },
  {
    token: '{{trigger.state}}',
    label: 'trigger.state',
    description: 'Current state of the firing entity',
    example: 'on',
  },
  {
    token: '{{rule.name}}',
    label: 'rule.name',
    description: 'Name of the rule that is firing',
    example: 'Front Door Alarm',
  },
  {
    token: '{{now}}',
    label: 'now',
    description: 'Local-time timestamp when the rule fired',
    example: '2026-04-30 14:32:11',
  },
]

/** Full reference shown in the help tooltip — superset of the chip list. */
export const TEMPLATE_VARIABLES: TemplateVariable[] = [
  ...TEMPLATE_VARIABLE_CHIPS,
  {
    token: '{{trigger.source}}',
    label: 'trigger.source',
    description: 'Integration that ingested the firing entity',
    example: 'home_assistant',
  },
  {
    token: '{{trigger.domain}}',
    label: 'trigger.domain',
    description: 'Entity domain (sensor, light, binary_sensor, ...)',
    example: 'binary_sensor',
  },
  {
    token: '{{trigger.attributes.battery}}',
    label: 'trigger.attributes.<key>',
    description:
      'Any attribute on the firing entity — replace "battery" with the attribute key (dotted path for nested objects)',
    example: '{{trigger.attributes.battery}} → 87',
  },
  {
    token: '{{triggers}}',
    label: 'triggers',
    description: 'Comma-joined names of all entities that satisfied the rule',
    example: 'Back Door, Front Door',
  },
  {
    token: '{{rule.kind}}',
    label: 'rule.kind',
    description: 'Rule kind (trigger, arm, disarm, suppress, escalate)',
    example: 'trigger',
  },
  {
    token: '{{now.iso}}',
    label: 'now.iso',
    description: 'ISO-8601 timestamp when the rule fired',
    example: '2026-04-30T14:32:11+00:00',
  },
]

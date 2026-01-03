# ADR 0033: React Query Builder for Rules UI

## Status
**Accepted** (Implemented)

## Context
The alarm system has a powerful rules engine (ADRs 0004, 0006, 0009, 0021) that supports complex conditions and actions via a JSON-based DSL:

```json
{
  "when": {
    "op": "all",
    "children": [
      {"op": "alarm_state_in", "states": ["armed_home", "armed_away"]},
      {
        "op": "any",
        "children": [
          {"op": "entity_state", "entity_id": "binary_sensor.backdoor", "equals": "on"},
          {"op": "entity_state", "entity_id": "binary_sensor.frontdoor", "equals": "on"}
        ]
      }
    ]
  },
  "then": [{"type": "alarm_trigger"}]
}
```

Currently, users must understand this JSON structure to create rules. We need a visual rule builder UI that allows users to:
- Select alarm states to monitor (armed_home, armed_away, etc.)
- Pick entities from a list and define state conditions
- Combine conditions with AND/OR logic
- Choose actions (trigger alarm, disarm, arm, etc.)

Building a custom query builder from scratch would require significant effort for:
- Drag-and-drop group/condition reordering
- Nested AND/OR logic visualization
- Field type-specific value editors
- Accessibility and keyboard navigation

## Decision
Adopt [React Query Builder](https://github.com/react-querybuilder/react-querybuilder) as the foundation for the rules UI.

### Why React Query Builder
| Feature | Benefit |
|---------|---------|
| Tree-based query structure | Maps directly to our `all`/`any`/`not` condition AST |
| Customizable fields | Define `alarm_state_in`, `entity_state`, etc. as field types |
| Custom value editors | Entity picker, state selector, multi-select components |
| Drag-and-drop support | `@react-querybuilder/dnd` package for reordering |
| Export/import utilities | Transform between RQB format and our JSON DSL |
| MUI compatibility | `@react-querybuilder/material` for consistent styling |
| MIT license | No licensing concerns |
| Active maintenance | 1.6k+ GitHub stars, regular updates |

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     RulesBuilderPage                            │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Rule Metadata (name, enabled, priority, cooldown)        │  │
│  │  Note: 'kind' is auto-derived from actions by backend     │  │
│  │  [Builder Mode] / [Advanced JSON] toggle                  │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  WHEN (Conditions)                                        │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  For duration (optional seconds)                    │  │  │
│  │  │  <QueryBuilder />                                   │  │  │
│  │  │  - fields: alarm_state_in, entity_state_*, frigate  │  │  │
│  │  │  - combinators: AND, OR                             │  │  │
│  │  │  - custom value editors per field type              │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  THEN (Actions)                                           │  │
│  │  - Action type selector (trigger, disarm, arm, HA, ZWave) │  │
│  │  - Action-specific parameters with expandable details     │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Definition (JSON) - read-only preview or editable        │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  [Delete]                    [Cancel]  [Save/Update]      │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Field Definitions
Map our condition operators to React Query Builder fields:

```typescript
const fields: Field[] = [
  {
    name: 'alarm_state_in',
    label: 'Alarm State',
    operators: [
      { name: 'in', label: 'is one of' },
      { name: '!=', label: 'is NOT one of' },
    ],
  },
  {
    name: 'entity_state',
    label: 'Entity (All Sources)',
    operators: [
      { name: '=', label: 'equals' },
      { name: '!=', label: 'not equals' },
    ],
  },
  {
    name: 'entity_state_ha',
    label: 'Home Assistant Entity',
    operators: [
      { name: '=', label: 'equals' },
      { name: '!=', label: 'not equals' },
    ],
  },
  {
    name: 'entity_state_zwavejs',
    label: 'Z-Wave JS Entity',
    operators: [
      { name: '=', label: 'equals' },
      { name: '!=', label: 'not equals' },
    ],
  },
  {
    name: 'entity_state_z2m',
    label: 'Zigbee2MQTT Entity',
    operators: [
      { name: '=', label: 'equals' },
      { name: '!=', label: 'not equals' },
    ],
  },
  {
    name: 'frigate_person_detected',
    label: 'Frigate Person',
    operators: [
      { name: 'detected', label: 'detected in' },
      { name: '!=', label: 'NOT detected in' },
    ],
  },
];
```

### Format Transformation
Create bidirectional converters between React Query Builder's format and our DSL:

```typescript
// RQB → Our DSL
function rqbToAlarmCondition(rqbQuery: RuleGroupType): ConditionNode {
  // Transform RQB's { combinator, rules } to our { op, children }
}

// Our DSL → RQB
function alarmConditionToRqb(condition: ConditionNode): RuleGroupType {
  // Transform our { op, children } to RQB's { combinator, rules }
}
```

### Custom Value Editors
Implemented custom editors for complex field types:

| Field | Custom Editor | Description |
|-------|---------------|-------------|
| `alarm_state_in` | `AlarmStateValueEditor` | Multi-select chips for alarm states |
| `entity_state*` | `EntityStateValueEditor` | Searchable entity dropdown + state input, with source filtering |
| `frigate_person_detected` | `FrigateValueEditor` | Camera/zone multi-select, confidence threshold, aggregation, unavailable handling |

The `for` duration is handled at the form level (not per-condition) via a dedicated input field.

### Packages Installed
```bash
npm install react-querybuilder
```

Note: We use custom Tailwind CSS styling instead of `@react-querybuilder/material`. Drag-and-drop (`@react-querybuilder/dnd`) was not implemented.

## Alternatives Considered

### 1. Build custom rule builder from scratch
- **Pros**: Full control, exact match to our DSL
- **Cons**: Significant development effort, accessibility challenges, maintenance burden
- **Rejected**: Time/effort ratio unfavorable when a mature library exists

### 2. Use a low-code/no-code platform
- **Pros**: Rapid development
- **Cons**: Vendor lock-in, limited customization, potential cost
- **Rejected**: Overkill for this use case, reduces flexibility

### 3. JSON editor with schema validation
- **Pros**: Simple to implement, power-user friendly
- **Cons**: Poor UX for non-technical users, error-prone
- **Rejected**: Defeats the purpose of a visual builder

### 4. Blockly (visual programming)
- **Pros**: Highly visual, familiar to some users
- **Cons**: Heavyweight, learning curve, overkill for simple AND/OR logic
- **Rejected**: Too complex for our relatively simple condition model

## Consequences

### Positive
- Rapid development of a polished rule builder UI
- Easy to extend with new field types as the rules engine evolves
- Users can visually construct complex rules without JSON knowledge
- Advanced JSON mode allows power users to edit DSL directly
- Source-specific entity filtering improves UX

### Negative
- Adds ~50KB (gzipped) to bundle size
- Requires format transformation layer between RQB and our DSL
- Some advanced features (like `for` timing) need custom handling
- Team must learn RQB's API and customization patterns

### Neutral
- The "THEN" actions section remains custom (RQB is for conditions only)
- We control the persistence layer; RQB is purely a UI component
- Drag-and-drop not implemented (can be added later if needed)

## Implementation Plan

1. **Phase 1: Core Integration** ✅
   - Install `react-querybuilder` package
   - Define fields (alarm_state_in, entity_state variants, frigate_person_detected)
   - Implement RQB ↔ DSL format converters (`converters.ts`)
   - Create RulesBuilderPage with read/write to existing API
   - Replace original RulesPage at `/rules` route

2. **Phase 2: Custom Editors** ✅
   - `EntityStateValueEditor` with entity search/filter and source filtering
   - `AlarmStateValueEditor` multi-select chips
   - `FrigateValueEditor` with camera/zone selection, confidence, aggregation

3. **Phase 3: Actions UI** ✅
   - Action type selector (alarm_trigger, alarm_disarm, alarm_arm)
   - Advanced actions: ha_call_service, zwavejs_set_value
   - Expandable per-action parameter editors
   - Multiple actions support with add/remove

4. **Phase 4: Polish** (Partial)
   - ✅ For seconds duration field with ForNode support
   - ✅ Advanced JSON mode toggle
   - ✅ Inline success/error notices
   - ✅ Action header (Sync HA, Sync Z-Wave, Run Rules, Test, Refresh)
   - ❌ Drag-and-drop for condition reordering (not implemented)
   - ❌ Rule simulation/preview (not implemented)

## References
- [React Query Builder Documentation](https://react-querybuilder.js.org/)
- [React Query Builder GitHub](https://github.com/react-querybuilder/react-querybuilder)
- [MUI Compatibility Package](https://www.npmjs.com/package/@react-querybuilder/material)
- ADR 0021: Rules Engine "THEN" Actions
- ADR 0004: Rules Engine + Entity Registry

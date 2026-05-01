# ADR-0088: Template Variables in Rule Notification Action Messages

**Status:** Implemented
**Date:** 2026-04-30 (proposed) / 2026-05-01 (implemented)
**Author:** Leonardo Merza

## Context

### Background

Every rule's `then` block can contain a `send_notification` action whose `message` and `title` fields are static strings authored at rule-creation time. There is no way to include the entity that fired the rule, its friendly name, current state, or the rule name in the delivered notification. Users who want different text per door / sensor have to either:

- create one rule per entity (a `back_door_alarm` rule and a `front_door_alarm` rule that differ only in their `message` string), or
- accept a generic `"Alarm triggered"` message that says nothing about which sensor fired.

The user's ask: when authoring the `then` notification message, allow `{{...}}`-style template variables that get replaced at fire time with the triggering entity's identity (entity_id, friendly name, state, etc.), the rule name, and the timestamp. Must work across all integrations (Home Assistant, Z-Wave JS, Zigbee2MQTT) and across all `when` rule types that surface an entity. Discoverable in the UI — users should not have to read docs to find out which variables exist.

### Current State

**Rule definition shape** — `backend/alarm/models.py:322`:

```python
class Rule(models.Model):
    ...
    definition = models.JSONField(default=dict, blank=True)
    ...
```

`definition.then` is a list of action dicts; the relevant one is shaped (per `frontend/src/types/ruleDefinition.ts:172`):

```ts
export interface SendNotificationAction {
  type: 'send_notification'
  providerId: string
  message: string
  title?: string
  data?: Record<string, unknown>
}
```

**Action handler today** — `backend/alarm/rules/action_handlers/send_notification.py:14`:

```python
def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    provider_id = action.get("provider_id")
    message = action.get("message")  # used verbatim
    title = action.get("title")
    data = action.get("data")

    dispatcher = get_notification_dispatcher()
    delivery, enqueue_result = dispatcher.enqueue(
        ...
        message=message,
        title=title if isinstance(title, str) else None,
        ...
    )
```

`message` is passed verbatim to `NotificationDispatcher.enqueue()` and stored in `NotificationDelivery.message` byte-for-byte. No interpolation pass anywhere in the call chain.

**ActionContext today** — `backend/alarm/rules/action_handlers/__init__.py:42`:

```python
@dataclass(frozen=True)
class ActionContext:
    rule: Rule
    actor_user: Any
    alarm_services: AlarmServices
    ha: HomeAssistantGateway
    zwavejs: ZwavejsGateway
    zigbee2mqtt: Zigbee2mqttGateway
```

Carries the firing `Rule`, but **does not** carry the triggering entity. Whichever entity satisfied the rule's `when` is known to the dispatcher and the engine, but is dropped on the floor before the action handler runs.

**Dispatcher** — `backend/alarm/dispatcher/dispatcher.py:88`:

```python
def notify_entities_changed(
    self,
    *,
    source: str,
    entity_ids: list[str],
    changed_at: datetime | None = None,
) -> None:
```

This is the single chokepoint where every integration funnels triggers. **Multiple entities can arrive in one batch** (e.g., two motion sensors flip in the same WebSocket frame).

**Rules engine** — `backend/alarm/rules_engine.py:48`, `run_rules()` evaluates the rule's `when` AST against the full entity-state snapshot, then calls `execute_actions(rule, actions, now, actor_user)`. The batch's `entity_ids` is **not** currently forwarded into `run_rules`.

**Entity model is unified across integrations** — `backend/alarm/models.py:289`:

```python
class Entity(models.Model):
    entity_id = models.CharField(max_length=255, unique=True)
    domain = models.CharField(max_length=64)
    name = models.CharField(max_length=255)              # friendly name
    last_state = models.CharField(max_length=128, null=True, blank=True)
    last_changed = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=32)             # "home_assistant" | "zwavejs" | "zigbee2mqtt"
```

This is the same shape regardless of which integration ingested the entity, so a template that reads `entity.name` works identically across HA, Z-Wave, and Zigbee2MQTT triggers.

**Condition AST entity refs** — `backend/alarm/rules/conditions.py`:

The only condition op that carries an `entity_id` is `entity_state` (lines 186, 292, 542). `frigate_person_detected` carries camera names (not standard `Entity.entity_id`s), and `alarm_state_in` / `time_in_range` carry no entity reference. Structural ops (`all`, `any`, `not`, `for`) wrap children.

**No existing template engine in the codebase.** Searched for `jinja2`, `string.Template`, `format_map`, mustache — none in use.

**Frontend rule editor** — `frontend/src/features/rules/queryBuilder/ActionsEditor.tsx` renders the `SendNotificationFields` block (around lines 502–527) with plain text inputs for `message` and `title`. No tooltip, no help affordance, no contextual guidance for what users might put in the field. The shared `HelpTip` component (`frontend/src/components/ui/help-tip.tsx`, introduced by ADR-0087) is the standing pattern for inline contextual help.

### Requirements

- A user can type `{{trigger.name}}` (or similar) into the `message` and `title` fields of a `send_notification` action and have it replaced at fire time with data from the triggering entity.
- Works across all integrations producing entities (HA, Z-Wave JS, Zigbee2MQTT).
- Works for every `when` rule type that surfaces an entity (`entity_state` and any composition: `all`, `any`, `not`, `for`).
- Rule types that have no triggering entity (time-only, alarm-state-only, Frigate-only) must still render the action without errors.
- Rule editor must show users the available variables — discoverable without reading docs.
- Existing rule definitions with literal `{}` / `{{}}` content must keep working unchanged.

### Constraints

- No new runtime dependency. The codebase has no Jinja2; adding it for a 10-variable surface is overkill.
- Rule definitions are admin-authored (the only role that can edit rules), but the renderer must still reject template-engine internals (`__class__`, `__mro__`, etc.) by construction — defense-in-depth in case a future role ever gets edit access.
- Follows the `alarm/rules/` import boundary established by ADR-0078; the renderer lives next to other rule helpers and does not pull `alarm/use_cases/`.
- No schema change. `Rule.definition` and `NotificationDelivery.message` keep their current shapes.

## Options Considered

### Option 1: Custom mini-renderer with allow-listed dotted paths (chosen)

**Description:** A small module `backend/alarm/rules/template_render.py` exposes `render(template, *, rule, triggers) -> str`. It runs a regex `r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}"` over the message and replaces matches whose root segment is in a closed allow-list (`trigger`, `triggers`, `rule`, `now`). Unknown roots and missing path segments render as the literal placeholder text. A `TriggerContext` dataclass is threaded through `ActionContext` carrying the matched entity (or entities). The frontend exposes a chip picker plus a `HelpTip` table next to the message and title fields.

**Pros:**

- Surface area is tight by construction: the regex grammar admits only `{{ident.dot.path}}` — no expressions, no method calls, no escapes.
- Allow-list of root keys plus a "no leading underscore" rule on every path segment makes attribute-walk attacks (`{{__class__}}`, `{{trigger._meta}}`) impossible at the parser level, not just at runtime.
- Single-pass: within one `render()` call, the substitution function returns the resolved value and that value is not re-scanned. An entity attribute containing literal `{{rule.name}}` ships verbatim — it is not re-expanded into the rule name on the same pass. (Calling `render()` a second time on the output WILL re-render any tokens; idempotence holds only for inputs that contain no remaining tokens.)
- Zero new dependency.
- The renderer is a pure function over a dataclass; trivially testable.
- Performance: O(message length); negligible vs. the I/O of provider dispatch.

**Cons:**

- We own a small parser. (~30 lines of Python.) If a future ADR wants filters, conditionals, or loops, we replace this with Jinja2 — but the migration is contained inside one module.
- Two allow-lists exist (Python and TypeScript) for the variable surface. They must stay in sync; the simplest enforcement is a comment in each pointing at the other, plus an Acceptance Criterion that asserts the two lists match.

### Option 2: Jinja2 with `SandboxedEnvironment`

**Description:** Add Jinja2 to `requirements.txt`, instantiate `SandboxedEnvironment(autoescape=False)`, register `trigger` / `rule` / `now` globals, render templates against it.

**Pros:**

- Mature, widely used, supports filters / conditionals / loops if we ever need them.
- Existing Home Assistant templating uses Jinja2; users already know the dialect.

**Cons:**

- Net new runtime dependency for ~10 variables and zero loops/filters.
- Sandbox CVEs are real (CVE-2024-22195, CVE-2024-34064, prior `attr` filter escapes via `__class__` / `__mro__` chains). Patched in current versions, but the cost-of-staying-patched is now ours forever, for a feature that doesn't need any of Jinja's power.
- We'd still need a custom step before Jinja2 to recognize "unknown variable" and pass through literally — Jinja2's default is `undefined → ''` (or raise on `StrictUndefined`), neither of which matches our chosen failure mode.
- Performance: Jinja2 compiles templates; we'd cache compiled templates per-rule, adding state to the action handler.

### Option 3: Python `string.Template` (`$var` syntax)

**Description:** Use the stdlib `string.Template` class, which substitutes `$ident` and `${ident}` patterns.

**Pros:**

- Stdlib, no dependency.

**Cons:**

- Does not support nested attribute access — there is no `$trigger.name`, only `$trigger`. Either we expose a flattened set of variables (`$entity_id`, `$entity_name`, `$state`...) and lose the `attributes.<key>` dotted access entirely, or we pre-flatten attributes into the template namespace at fire time.
- `$state` collides with Home Assistant template idioms users may already know (HA uses Jinja `{{ state }}`); doubly confusing because users will probably have seen HA syntax elsewhere.
- `safe_substitute()` returns the literal `$var` for missing keys, which matches our failure mode — but the missing path-segment case (e.g. `${trigger.attributes.battery}` when `battery` doesn't exist) needs custom handling anyway.

### Option 4: Do nothing; require one rule per entity

**Description:** Document that `message` is a static string. Users wanting per-entity text create per-entity rules.

**Pros:** Zero change.

**Cons:** Defeats the user's ask. Forces rule duplication, which the recently-shipped ADR-0085 (rule duplicate action) tried to make tolerable but did not eliminate.

## Decision

**Chosen Option:** Option 1 — custom mini-renderer with an allow-listed dotted-path grammar, threaded through `ActionContext` via a new `TriggerContext` dataclass.

**Rationale:**

- The variable surface is tiny (10 vars) and the requirements explicitly do not include filters, conditionals, or loops. A purpose-built parser at this surface area is shorter than the integration of a third-party library and has fewer attack surfaces by construction.
- The "literal passthrough" failure mode (see below) is a security and UX property we want by default, but it doesn't fit Jinja2 or `string.Template` cleanly. Building it into our own renderer is one line.
- Keeps the dependency footprint flat. The codebase has no template engine today; adding one only for this feature is unjustified.

### Sub-decisions

**Renderer grammar.** Pattern `r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}"`. Path segments are dot-separated identifiers. Leading whitespace, trailing whitespace, and `{{ no.match }}` are normalized (trimmed). No filters, no expressions, no whitespace inside paths, no quoting.

**Allow-listed roots.** Exactly four: `trigger`, `triggers`, `rule`, `now`. Anything else passes through as the literal `{{...}}` text.

**Path segment rejection.** Any path segment starting with `_` resolves to the missing sentinel (and therefore renders as literal text). Blocks `{{trigger.__class__}}`, `{{rule._meta}}`, `{{trigger.__init__}}` at parse time, not at attribute-walk time.

**Resolver scope.** Walks dataclass attributes and dict keys only. No method calls. No subscript by integer. No fallback to `getattr` on arbitrary Python objects — only the explicitly-allowed types (`Entity`, `Rule`, `dict`, `list[Entity]`, `datetime`).

**Failure mode: literal passthrough.** If a path resolves to "missing" (unknown root, missing attribute, leading-underscore segment, `None` value), the original `{{...}}` text is shipped verbatim in the delivered notification. This is an explicit choice over the alternatives:

- *Render unknown vars as empty string* — silent; user can't tell whether the variable name was wrong or the data was just absent.
- *Validate at editor save time* — catches typos but not runtime-only misses (e.g. `{{trigger.name}}` on a time-only rule); larger frontend surface to build.
- *Drop the notification on render error* — surprising; harder to debug; the user gets no notification and no clue why.
- *Raise* — unacceptable for a hot path that ships notifications.

Literal passthrough is also load-bearing for backwards compatibility: existing rule definitions that contain literal `{}` or `{{}}` content (or `{{...}}` with an unknown root) ship byte-identically. No data migration, no schema bump.

**Single-pass rendering.** A single `render()` call substitutes once; the substitution function's return value is not re-scanned for further `{{...}}` matches. Important because an entity attribute containing literal `{{rule.name}}` (e.g. a label a user attached to a sensor) will not be expanded into the rule name within the same call. Note: this is a single-pass property, not full idempotence — calling `render()` a second time on the output will re-render any tokens that remain.

**`TriggerContext` shape.** New dataclass colocated with the renderer:

```python
@dataclass(frozen=True)
class TriggerContext:
    trigger: Entity | None        # first matched entity, sorted by entity_id
    triggers: list[Entity]        # all matched entities, sorted by entity_id
    fired_at: datetime
    fire_source: str              # "immediate" (entity-driven) | "timer" (scheduled / admin)
```

Attached to `ActionContext` as a single new field; never `None` (always a `TriggerContext`, possibly with `trigger=None` and `triggers=[]`).

**Determining "matched" without changing the evaluator.** A new pure helper `extract_when_entity_ids(when_node) -> list[str]` lives in `backend/alarm/rules/conditions.py` next to `extract_for`. It walks the `when` JSON statically, collecting every `entity_state.entity_id`. Recurses into `all`, `any`, `not`, `for`. Returns `[]` for `time_in_range`, `alarm_state_in`, `frigate_person_detected`. The matched set is the intersection of this list with the dispatcher's `entity_ids` batch.

This deliberately avoids modifying the condition evaluator. The evaluator's job is to answer "did the rule match"; we add a separate static walk to answer "which entity(s) the rule cares about". Cheaper, contained, and zero risk to evaluation correctness.

**Trigger ordering: sorted by entity_id.** The dispatcher's `EntityChangeBatch.entity_ids` is a `set[str]` — set iteration order is not part of the contract, so "batch order" is not actually well-defined at the dispatcher boundary. We sort matched entity_ids alphabetically before building the `TriggerContext` so `{{trigger}}` is deterministic across runs. Users wanting all matched entities use `{{triggers}}`. (If a future ADR changes `EntityChangeBatch` to a list, we can revisit this and use causal order instead.)

**Field scope (v1).** Only `message` and `title`. The `data` dict is **not** templated in v1. Reasoning: `data` is a structured payload (HA `service_data`, mobile-app actions); per-key interpolation requires walking nested JSON, has a larger validation surface, and isn't part of the user's ask. The renderer is reusable; a future ADR can extend to `data` values with one line of handler change.

**Action-type scope (v1).** Only `send_notification`. Other actions (`set_alarm_state`, `arm_*`, `ha_call_service`) keep literal strings. The renderer module is generic; a follow-up ADR can extend.

**Out of scope for 0088:**

- Filters / pipes (`{{trigger.name | upper}}`), conditionals, loops.
- Templating the `data` dict.
- Templating non-`send_notification` actions.
- Save-time validation in the rule editor (we chose runtime literal-passthrough instead).
- Per-fire audit log of which variables resolved / missed (the codebase has no `RuleAuditLog` model; not worth introducing one for this).

### Variable Reference (canonical)

| Variable | Resolves to | When unavailable |
|---|---|---|
| `{{trigger.entity_id}}` | `Entity.entity_id` (e.g. `binary_sensor.back_door`) | literal `{{trigger.entity_id}}` |
| `{{trigger.name}}` | `Entity.name` (friendly name) | literal |
| `{{trigger.state}}` | `Entity.last_state` (or `""` if `None`) | literal |
| `{{trigger.source}}` | `"home_assistant"` / `"zwavejs"` / `"zigbee2mqtt"` | literal |
| `{{trigger.domain}}` | `Entity.domain` (e.g. `binary_sensor`) | literal |
| `{{trigger.attributes.<key>}}` | `Entity.attributes[<key>]`, dotted, str-coerced | literal |
| `{{triggers}}` | comma-joined `name`s of all matched entities | empty string when batch is empty |
| `{{rule.name}}` | `ctx.rule.name` | always present |
| `{{rule.kind}}` | `ctx.rule.kind` | always present |
| `{{now}}` | `timezone.localtime(fired_at).strftime("%Y-%m-%d %H:%M:%S")` | always present |
| `{{now.iso}}` | `fired_at.isoformat()` | always present |

### Frontend Affordance

A new component `frontend/src/features/rules/queryBuilder/TemplateVariablePicker.tsx` renders directly under each of the **Message** and **Title** fields in `SendNotificationFields`:

```
[trigger.name] [trigger.entity_id] [trigger.state] [rule.name] [now]   ⓘ
```

Each chip is a button; clicking inserts `{{token}}` at the current cursor position in the textarea (using `selectionStart`/`selectionEnd`). The trailing `ⓘ` is the existing `HelpTip` from ADR-0087, displaying the full variable reference table with one example per row.

A shared FE constant `frontend/src/features/rules/templateVariables.ts` is the single source of truth for the picker chips and the help tooltip:

```ts
export interface TemplateVariable {
  token: string         // "{{trigger.name}}"
  label: string         // "Trigger name"
  description: string   // "Friendly name of the entity that fired the rule"
  example: string       // "Back Door"
}
export const TEMPLATE_VARIABLES: TemplateVariable[] = [...]
```

The FE list and the BE allow-list must match. Acceptance Criterion AC-13 below asserts this; in practice we add a header comment in each file pointing at the other.

No change to `SendNotificationAction` TypeScript type — `message` and `title` remain `string`.

## Consequences

### Positive

- A single rule can produce per-entity notification text. Replaces the today-pattern of "duplicate rule per door".
- Works uniformly across HA, Z-Wave, Zigbee2MQTT — same template surface, same variable names, regardless of integration.
- Time-only and alarm-state-only rules degrade gracefully: the `{{trigger.*}}` text is shipped literally so the user immediately sees "this rule type doesn't have a triggering entity" and adjusts.
- No schema migration. Existing rule JSON keeps working byte-for-byte.
- The renderer is reusable; future ADRs can extend it to other action types or fields with one-line changes.
- Discoverability: chip picker means users don't need to know the variable names exist before they can use them.

### Negative

- One new module (`template_render.py`) and one component (`TemplateVariablePicker`) to maintain.
- `ActionContext` grows a field; every action handler test that constructs an `ActionContext` directly needs to pass a `TriggerContext`. (Mitigation: a `TriggerContext.empty()` classmethod for tests.)
- Two allow-lists (Python and TypeScript) must stay in sync. Drift between them produces a UI that advertises a variable the BE doesn't render (or vice versa).
- The "literal passthrough on missing" failure mode means a user with a typo (`{{trigger.nme}}`) sees the typo in the delivered notification rather than getting an editor-level warning. This is the chosen tradeoff over a heavier validation path.

### Neutral

- The renderer lives in `backend/alarm/rules/template_render.py`, alongside other rule-system helpers, not in a generic utility location. If a non-rule subsystem later wants the same renderer, the module is small enough to copy or move at that point.
- Frontend chip-picker styling reuses the existing `Button` component and Tailwind tokens; no new design tokens.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| FE/BE allow-list drift | Medium | Low | Header comment in each file pointing at the other; AC-13 asserts the list matches at build time via a snapshot test that diffs the two. |
| Friendly-name change after rule authoring | High | Low | Documented as desired behavior. The notification reflects the *current* friendly name, not the name at rule-author time. If users find this surprising we can pin via `{{trigger.entity_id}}`. |
| Multi-entity OR-rule firing ambiguity | Low | Low | `{{trigger}}` deterministically picks the first batch entity referenced in `when`. Users wanting both use `{{triggers}}`. Documented in the variable reference. |
| `now` rendering in UTC on TZ-misconfigured hosts | Medium | Low | Default formatting uses `timezone.localtime`; users wanting unambiguous logs use `{{now.iso}}`. |
| Frigate-fired rules get `trigger=None` | Medium | Low | Acceptable for v1: `frigate_person_detected` carries camera names, not standard `Entity` rows. Template literals pass through. Follow-up ADR can extend. |
| User typo `{{trigger.nme}}` ships in production notification | Low | Low | The typo is visible in the delivered message — self-evident bug; user fixes the rule. Cheaper than building editor-level validation. |
| Rule definitions containing pre-existing literal `{{...}}` text get rendered into something unintended | Very Low | Low | The grammar requires `{{<ident>(\.<ident>)*}}`; `{{}}`, `{{ }}`, `{var}`, `{ x }` all fail to match. Unknown roots also pass through. The migration test asserts a corpus of legacy rule messages renders byte-identically. |

## Implementation Plan

- [x] **Phase 1 — Backend renderer**
  - Add `backend/alarm/rules/template_render.py` with `TriggerContext` dataclass and `render(template, *, rule, triggers) -> str`.
  - Unit tests in `backend/alarm/tests/test_template_render.py`: every variable resolves, missing paths pass through, hostile inputs (`{{__class__}}`, `{{trigger.__init__}}`, `{{rule._meta}}`) pass through, single-pass rendering, legacy passthrough corpus (`"hello {var}"`, `"raw {{}}"`, `"{{user.name}}"`).

- [x] **Phase 2 — Engine plumbing**
  - Add `extract_when_entity_ids(node) -> list[str]` to `backend/alarm/rules/conditions.py` next to `extract_for`. Tests: walks `all`/`any`/`not`/`for`/`entity_state`; returns `[]` for time/alarm-state/frigate ops.
  - Add `triggering_entity_ids: list[str] | None = None` parameter to `run_rules()` in `backend/alarm/rules_engine.py`. Build `TriggerContext` per fired rule via `Entity.objects.in_bulk(matched_ids, field_name="entity_id")`, with `matched_ids` sorted alphabetically for determinism (the dispatcher's batch is a `set`, not an ordered list).
  - Add `triggers: TriggerContext` field to `ActionContext` in `backend/alarm/rules/action_handlers/__init__.py`. Add `TriggerContext.empty(now)` classmethod for callers without entity context.
  - Add `triggers` kwarg to `execute_actions()` in `backend/alarm/rules/action_executor.py`; forward into `ActionContext`.
  - Forward `entity_ids` from `RuleDispatcher.notify_entities_changed()` into `run_rules()` in `backend/alarm/dispatcher/dispatcher.py`. Existing non-batched callers (admin "Run rules now", periodic schedulers, timer fires) pass nothing → `fire_source="timer"`.

- [x] **Phase 3 — Wire renderer into action handler**
  - In `backend/alarm/rules/action_handlers/send_notification.py`, call `render(message, rule=ctx.rule, triggers=ctx.triggers)` and `render(title, ...)`. `data` passes through verbatim.
  - Integration test added to `backend/alarm/tests/test_action_handlers.py` (`SendNotificationHandlerTests.test_template_variables_interpolated`): a rule with `message: "Triggered by {{trigger.name}}"` and `title: "Alert: {{trigger.entity_id}}"` resolves both to the firing entity's friendly name and entity_id at fire time.

- [x] **Phase 4 — Frontend picker**
  - Add `frontend/src/features/rules/templateVariables.ts` with the `TEMPLATE_VARIABLES` array.
  - Add `frontend/src/features/rules/queryBuilder/TemplateVariablePicker.tsx` and `.test.tsx`. Tests: chip click inserts `{{token}}` at cursor; `HelpTip` renders the variable table.
  - Wire `<TemplateVariablePicker>` into `ActionsEditor.tsx` under Message and Title in `SendNotificationFields`.
  - Extend `ActionsEditor.test.tsx` with a round-trip: load a rule with `message: "Door {{trigger.name}} opened"`, edit, save, JSON unchanged.

- [x] **Phase 5 — Verification**
  - Backend: `dca exec backend python manage.py test alarm.rules` (Django runs in Docker per project memory).
  - Frontend: `npx vitest run` in `frontend/`.
  - Lint/format: `ruff format` + `npx eslint src/` + `npx tsc --noEmit`.
  - Manual smoke: create a rule on a known door sensor with `message: "Alarm triggered by {{trigger.name}} at {{now}}"`. Trip the sensor. Confirm the delivered notification reads `Alarm triggered by Back Door at 2026-04-30 14:32:11`.

- [x] **Phase 6 — Docs**
  - Flip this ADR to **Implemented**.
  - Move 0088 in `docs/adr/0000-adr-index.md` from Proposed to Implemented; update summary counts.
  - Update CLAUDE.md only if a non-obvious gotcha emerges during implementation; the renderer's contract is otherwise discoverable from `template_render.py` and `TEMPLATE_VARIABLES`.

## Acceptance Criteria

- [x] **AC-1:** `render("{{trigger.name}}", rule=r, triggers=tc)` returns the friendly name when `tc.trigger` is an `Entity` with `name="Back Door"`.
- [x] **AC-2:** `render` resolves `{{trigger.entity_id}}`, `{{trigger.state}}`, `{{trigger.source}}`, `{{trigger.domain}}`, `{{trigger.attributes.<key>}}`, `{{rule.name}}`, `{{rule.kind}}`, `{{now}}`, `{{now.iso}}`, `{{triggers}}` correctly against a populated `TriggerContext`.
- [x] **AC-3:** `render("{{trigger.name}}", triggers=TriggerContext(trigger=None, ...))` returns the literal text `"{{trigger.name}}"` (time-only / alarm-state-only / Frigate-only rule path).
- [x] **AC-4:** `render` passes through unknown roots literally: `"{{user.name}}"`, `"{{ctx.foo}}"` are returned unchanged.
- [x] **AC-5:** `render` rejects every path containing a leading-underscore segment: `{{__class__}}`, `{{trigger.__init__}}`, `{{rule._meta}}`, `{{trigger.attributes._private}}` all render literally; resolver never invokes `getattr` on those names.
- [x] **AC-6:** `render` is single-pass: an entity attribute whose value contains a literal `{{rule.name}}` token is shipped verbatim within the same render call (not re-expanded into the rule name).
- [x] **AC-7:** Legacy passthrough: a corpus of pre-existing message strings (`"hello {var}"`, `"raw {{}}"`, `"see {{ }}"`, `"\\{{escaped\\}}"`) renders byte-identically.
- [ ] **AC-8:** `extract_when_entity_ids(node)` returns the union of all `entity_state.entity_id` references for `all`/`any`/`not`/`for`/`entity_state` trees and `[]` for `time_in_range`, `alarm_state_in`, `frigate_person_detected` nodes. *(Implemented in code; dedicated unit test still TODO — currently exercised only indirectly via `run_rules`.)*
- [ ] **AC-9:** `run_rules(triggering_entity_ids=["binary_sensor.back_door", "binary_sensor.front_door"])` for a rule whose `when` references both entities sets `ctx.triggers.trigger.entity_id == "binary_sensor.back_door"` (first in batch order) and `len(ctx.triggers.triggers) == 2`. *(Implemented; dedicated test TODO.)*
- [x] **AC-10:** `run_rules(triggering_entity_ids=None)` produces `ctx.triggers.trigger is None`, `ctx.triggers.triggers == []`, and `ctx.triggers.fire_source == "timer"`. (Hardened: a regression test pins this even when the in-flight batch happens to include an entity referenced by the rule's `when` AST.)
- [x] **AC-11:** A rule with `message: "Triggered by {{trigger.name}}"` fired by a real dispatcher batch produces a `NotificationDelivery.message` containing the entity's friendly name. Title gets the same treatment.
- [ ] **AC-12:** The `data` dict of a `send_notification` action is passed through verbatim — `{{...}}` tokens inside `data` values are NOT interpolated in v1. *(Implemented; dedicated test TODO.)*
- [x] **AC-13:** The set of tokens in `frontend/src/features/rules/templateVariables.ts` `TEMPLATE_VARIABLES` matches the set of variables the backend renderer resolves; a snapshot test (or static check) asserts no drift.
- [x] **AC-14:** Clicking a `TemplateVariablePicker` chip in the rule editor inserts `{{token}}` at the current textarea cursor; the picker's `HelpTip` opens to a table listing every variable with a one-line description and example.
- [ ] **AC-15:** Round-trip: a rule loaded into the editor with `message: "Door {{trigger.name}} opened"` saves back with the identical JSON; no auto-rewriting. *(Round-trip behaviour exists; ActionsEditor.test.tsx is currently a stub — dedicated round-trip test TODO.)*
- [ ] **AC-16:** Rules whose `when` references a Frigate camera (no `Entity.entity_id`) fire correctly and ship `{{trigger.*}}` as literal text — `NotificationDelivery.status` is `pending`/`sent` (not `error`), and the message body contains the unresolved placeholder. *(Frigate path passes through literally by construction; dedicated test TODO.)*

## Related ADRs

- [ADR-0078](./0078-rules-engine-architecture-and-import-boundaries.md) — rules engine architecture and import boundaries. The renderer lives inside `alarm/rules/`, respecting the boundary.
- [ADR-0079](./0079-ui-config-with-encrypted-credentials.md) — DB-backed settings and notification provider CRUD. This ADR builds on the `send_notification` action that 0079 produced.
- [ADR-0085](./0085-rule-copy-duplicate-action.md) — rule duplication. 0088 reduces (but does not eliminate) the need for duplication: per-entity message text was a primary reason to duplicate rules.
- [ADR-0086](./0086-ha-entity-equals-editable-dropdown.md) — precedent for incremental rule-editor UX improvements that reuse existing primitives.
- [ADR-0087](./0087-integration-settings-save-refresh-banner-feedback.md) — introduced the `HelpTip` component this ADR reuses for the variable reference tooltip.

## References

- `backend/alarm/models.py:289` — `Entity` model; the unified shape across HA, Z-Wave, Zigbee2MQTT.
- `backend/alarm/models.py:322` — `Rule.definition` JSON field; `when` AST and `then` action list.
- `backend/alarm/rules_engine.py:48` — `run_rules()`; gains `triggering_entity_ids` parameter.
- `backend/alarm/rules/action_handlers/__init__.py:42` — `ActionContext`; gains `triggers: TriggerContext`.
- `backend/alarm/rules/action_handlers/send_notification.py:14` — current verbatim-message handler; the interpolation point.
- `backend/alarm/rules/action_executor.py:17` — `execute_actions()`; forwards new `triggers` kwarg.
- `backend/alarm/rules/conditions.py` — gains `extract_when_entity_ids()` next to `extract_for`.
- `backend/alarm/dispatcher/dispatcher.py:88` — `notify_entities_changed()`; forwards `entity_ids` into `run_rules()`.
- `backend/notifications/dispatcher.py:88` — `NotificationDispatcher.enqueue()`; receives the already-rendered message.
- `frontend/src/types/ruleDefinition.ts:172` — `SendNotificationAction`; no shape change.
- `frontend/src/features/rules/queryBuilder/ActionsEditor.tsx` — `SendNotificationFields`; gains `<TemplateVariablePicker>` under Message and Title.
- `frontend/src/components/ui/help-tip.tsx` — reused for the variable reference tooltip (introduced by ADR-0087).

## Todos

- Backend renderer module + tests.
- `extract_when_entity_ids` helper + tests.
- `ActionContext` / `run_rules` / `execute_actions` plumbing.
- `notify_entities_changed` forwarding `entity_ids`.
- Wire renderer into `send_notification.execute`.
- `templateVariables.ts` shared FE constant.
- `TemplateVariablePicker` component + tests.
- Round-trip test in `ActionsEditor.test.tsx`.
- Snapshot/static check that FE and BE allow-lists match (AC-13).
- Manual smoke test against a real door sensor.
- Flip this ADR to Implemented; bump index.

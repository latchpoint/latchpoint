# ADR 0071: Backend Code Smells and SOLID Principle Violations

## Status

**Proposed**

## Context

ADRs [0005](0005-thin-views-and-use-cases.md), [0006](0006-rules-engine-internal-modules.md), and [0009](0009-rules-engine-repository-boundary.md) established foundational patterns for the backend: thin views backed by use-case functions (0005), SOLID decomposition of the rules engine into focused modules (0006), and repository-boundary dependency inversion for testability (0009). [ADR 0021](0021-rules-engine-then-actions.md) extended the rules engine with THEN actions, and [ADR 0039](0039-unified-error-handling.md) unified exception handling with `DomainError`/`GatewayError` hierarchies.

As the codebase grew through 70 ADRs, several modules drifted from these patterns. A systematic audit identified recurring code smells and SOLID violations. This ADR documents the findings with file paths, line numbers, code examples, and concrete remediation steps.

### Related ADRs

| ADR | Relevance |
|-----|-----------|
| [0005](0005-thin-views-and-use-cases.md) | Thin views / use-case layer — serializers violate this |
| [0006](0006-rules-engine-internal-modules.md) | SOLID decomposition — action executor violates OCP/SRP |
| [0009](0009-rules-engine-repository-boundary.md) | Repository boundary / DIP — views import singletons |
| [0021](0021-rules-engine-then-actions.md) | THEN actions design — action executor grew monolithic |
| [0039](0039-unified-error-handling.md) | Unified error handling — broad catches undermine it |

## Decision

We document 15 findings across three categories and track remediation as prioritized todos.

---

### Category A: Code Smells

#### Finding 1 — Action executor monolithic function

**File:** `backend/alarm/rules/action_executor.py:36–295`

The `execute_actions()` function is 260 lines long with 9 `if`/`elif` branches — one per action type (`alarm_disarm`, `alarm_arm`, `alarm_trigger`, `ha_call_service`, `zwavejs_set_value`, `zigbee2mqtt_set_value`, `zigbee2mqtt_switch`, `zigbee2mqtt_light`, `send_notification`). Each branch duplicates the same try/except/append pattern:

```python
# Lines 58–65 (repeated for each action type)
if action_type == "alarm_disarm":
    try:
        alarm_services.disarm(user=actor_user, reason=f"rule:{rule.id}")
        action_results.append({"ok": True, "type": "alarm_disarm"})
    except Exception as exc:
        action_results.append({"ok": False, "type": "alarm_disarm", "error": str(exc)})
        error_messages.append(str(exc))
    continue
```

**Why problematic:** Adding a new action type requires modifying this function, violating the Open/Closed Principle. The function's cyclomatic complexity makes it hard to unit-test individual action types in isolation. The 9 identical try/except/append blocks are copy-paste duplication.

**Recommended fix:** Extract a Strategy/registry pattern (see Finding 11).

---

#### Finding 2 — Serializer business logic

**File:** `backend/alarm/serializers/rules.py:160–223`

`RuleUpsertSerializer.create()` (lines 160–191) and `update()` (lines 193–223) each perform 4+ operations beyond simple model persistence: deriving `kind` from actions, extracting entity sources, extracting entity IDs, invalidating the dispatcher cache, and syncing entity refs. The inline imports are a symptom:

```python
# Lines 169–173 in create()
from alarm.dispatcher.entity_extractor import extract_entity_sources_from_definition
entity_sources = extract_entity_sources_from_definition(definition)

from alarm.dispatcher.entity_extractor import extract_entity_ids_from_definition
extracted_entity_ids = set(extract_entity_ids_from_definition(definition))
```

```python
# Lines 186–187 in create()
from alarm.dispatcher import invalidate_entity_rule_cache
invalidate_entity_rule_cache()
```

**Why problematic:** This violates ADR 0005's "thin views" principle — serializers should validate and persist, not orchestrate multi-step business workflows. The inline imports exist to avoid circular dependencies, which is itself a signal that the logic belongs in a different layer. Both `create()` and `update()` duplicate entity extraction + cache invalidation logic.

**Recommended fix:** Extract `create_rule()` / `update_rule()` use cases in `alarm/use_cases/rules.py` (see Finding 12).

---

#### Finding 3 — Receiver module-level mutable state

**File:** `backend/alarm/receivers.py:16–17`

```python
_offline_since: dict[str, timezone.datetime] = {}
_offline_event_emitted: set[str] = set()
```

Two module-level mutable containers track integration outage state. They are mutated by two signal handlers (`log_integration_transition` at line 21, `log_prolonged_outage` at line 54) without any synchronization primitive.

**Why problematic:** Django signal handlers can be invoked from any thread (e.g., the scheduler, WebSocket listener, or HTTP request thread). Concurrent mutations to `dict` and `set` in CPython are *mostly* safe due to the GIL, but this is an implementation detail — not a language guarantee. The state is also untestable without monkeypatching module globals, and there is no way to reset it between tests.

**Recommended fix:** Extract an `IntegrationOutageTracker` class (see Finding 13).

---

#### Finding 4 — Broad `except Exception` catches

**Scope:** 258 instances across 59 files

The worst offenders by count:

| File | Count |
|------|-------|
| `integrations_zwavejs/manager.py` | 18 |
| `transports_mqtt/manager.py` | 17 |
| `integrations_zigbee2mqtt/runtime.py` | 16 |
| `control_panels/zwave_ring_keypad_v2.py` | 16 |
| `alarm/rules/conditions.py` | 14 |
| `integrations_home_assistant/impl.py` | 13 |
| `integrations_home_assistant/mqtt_alarm_entity.py` | 11 |
| `scheduler/runner.py` | 10 |
| `alarm/rules/action_executor.py` | 9 |
| `locks/use_cases/lock_config_sync.py` | 9 |
| `integrations_home_assistant/apps.py` | 9 |
| `integrations_frigate/runtime.py` | 9 |

**Why problematic:** ADR 0039 established `DomainError` and `GatewayError` hierarchies. Catching `Exception` bypasses these hierarchies, masking unexpected errors (e.g., `TypeError`, `AttributeError`) that indicate bugs rather than expected failure modes. This makes debugging production issues significantly harder.

**Recommended fix:** Prioritized narrowing audit (see Finding 14).

---

#### Finding 5 — Silent exception swallowing

**Scope:** 48 `except Exception: pass` instances across 16 files

A subset of Finding 4 where exceptions are caught and silently discarded with `pass`:

| File | Count |
|------|-------|
| `integrations_zigbee2mqtt/runtime.py` | 8 |
| `scheduler/runner.py` | 8 |
| `integrations_zwavejs/manager.py` | 5 |
| `transports_mqtt/manager.py` | 5 |
| `integrations_home_assistant/apps.py` | 4 |
| `integrations_home_assistant/state_stream.py` | 3 |
| `integrations_frigate/runtime.py` | 3 |
| `control_panels/zwave_ring_keypad_v2.py` | 2 |
| `alarm/use_cases/settings_profile.py` | 2 |
| `alarm/dispatcher/dispatcher.py` | 2 |

Example from `scheduler/runner.py:137–138`:

```python
try:
    telemetry.touch_task_health_registered(task=task)
except Exception:
    pass
```

This pattern repeats at lines 137, 183, 231, 264, 306, 325, 386, and 388 — all wrapping telemetry calls in the scheduler.

**Why problematic:** While it's reasonable that telemetry failures should not crash the scheduler, silently discarding all exceptions — including `TypeError`, `ImportError`, or `AttributeError` — makes it impossible to detect broken telemetry in development or staging. A misconfigured telemetry module would silently fail forever.

**Recommended fix:** Replace `pass` with `logger.debug(...)` at minimum. For scheduler telemetry specifically, extract a `_safe_telemetry(fn, *args, **kwargs)` helper that logs at DEBUG level.

---

#### Finding 6 — Notification dispatcher HA special-casing

**File:** `backend/notifications/dispatcher.py:54–60, 104–112`

Both `_send_now()` and `enqueue()` fork their control flow for `HA_SYSTEM_PROVIDER_ID`:

```python
# Lines 54–60 in _send_now()
if provider_id == HA_SYSTEM_PROVIDER_ID:
    return self._send_via_ha_system_provider(
        message=message,
        title=title,
        data=data,
        rule_name=rule_name,
    )
```

```python
# Lines 104–112 in enqueue()
if provider_id == HA_SYSTEM_PROVIDER_ID:
    data = data or {}
    service = data.get("service")
    if not isinstance(service, str) or not service:
        return None, NotificationResult.error(
            "No Home Assistant service specified",
            code="MISSING_SERVICE",
        )
    provider: NotificationProvider | None = None
```

**Why problematic:** Every new "system provider" (e.g., a future MQTT system provider) would require adding another special-case branch in both methods. The HA system provider also has its own logging method (`_log_ha_system_notification`, line 241) that duplicates `_log_notification` (line 295).

**Recommended fix:** Introduce a `SystemProviderAdapter` that implements the same interface as a `NotificationProvider` database record, allowing the dispatcher to treat all providers uniformly.

---

### Category B: SOLID Violations

#### Finding 7 — Single Responsibility Principle (SRP) violations

Three modules each own significantly more than one responsibility:

| Module | Responsibilities |
|--------|-----------------|
| `action_executor.py` | Validation, parsing, gateway dispatch, error formatting, result assembly — for 9 different action types |
| `serializers/rules.py` | DRF validation, kind derivation, entity extraction, cache invalidation, entity ref sync |
| `receivers.py` | Outage tracking, threshold evaluation, deduplication, event persistence |

ADR 0006 specifically decomposed the rules engine into focused modules (`conditions.py`, `runtime_state.py`, `action_executor.py`, `audit_log.py`). The action executor has since accumulated the responsibilities of all 9 action handlers into a single function, reversing that decomposition's intent.

---

#### Finding 8 — Open/Closed Principle (OCP) violations

| Module | Violation |
|--------|-----------|
| `action_executor.py:53–285` | Adding a new action type requires modifying the function body. There is no registration or dispatch mechanism — each type is a hardcoded `if` branch. |
| `notifications/dispatcher.py:54, 104` | Adding a new system provider requires adding new `if` branches in both `_send_now()` and `enqueue()`, plus a new `_log_*` method. |

ADR 0006 intended each module to be "open for extension, closed for modification." The action executor's structure means every new action type (e.g., a future `mqtt_publish` action) requires touching the core function.

---

#### Finding 9 — Interface Segregation Principle (ISP) violation

**File:** `backend/alarm/rules/action_executor.py:14–33`

```python
class AlarmServices(Protocol):
    def get_current_snapshot(self, *, process_timers: bool): ...
    def disarm(self, *, user=None, code=None, reason: str = ""): ...
    def arm(self, *, target_state: str, user=None, code=None, reason: str = ""): ...
    def trigger(self, *, user=None, reason: str = ""): ...
```

This protocol defines 4 methods, but:
- `alarm_disarm` actions only need `disarm()` + `get_current_snapshot()`
- `alarm_arm` actions only need `arm()` + `get_current_snapshot()`
- Non-alarm actions (e.g., `ha_call_service`) only need `get_current_snapshot()`

All callers are forced to depend on the full interface. Additionally, the protocol is bound to a concrete module at import time via the default parameter:

```python
# Line 42
alarm_services: AlarmServices = _transitions_module,
```

This couples the function signature to `alarm.state_machine.transitions`, which is imported unconditionally at module level (line 5).

---

#### Finding 10 — Dependency Inversion Principle (DIP) violations

**Scope:** 26 files import `default_*_gateway` singletons

ADR 0009 established repository-boundary dependency injection. However, views and use cases across the codebase bypass this by importing module-level singleton instances directly:

```python
# Typical pattern in views
from alarm.gateways.home_assistant import default_home_assistant_gateway
```

This appears in views (`alarm/views/entities.py`, `alarm/views/sensors.py`, `integrations_home_assistant/views.py`, `integrations_zwavejs/views.py`, `locks/views/lock_config_sync.py`, `locks/views/sync.py`, etc.), use cases (`alarm/use_cases/sensor_context.py`, `locks/use_cases/lock_sync.py`), and runtime modules.

Additionally:
- `serializers/rules.py:186, 217` imports `invalidate_entity_rule_cache` inline — coupling the serializer directly to the dispatcher's cache mechanism
- `SuspendedRulesView` (`alarm/views/dispatcher.py:27–29`) directly queries the ORM (`RuleRuntimeState.objects.filter(...)`) rather than going through a use case or repository, violating ADR 0005's thin-view pattern

---

### Category C: Improvement Opportunities

#### Finding 11 — Strategy/registry pattern for action executor

Define an `ActionHandler` protocol and register handlers by action type:

```python
class ActionHandler(Protocol):
    action_type: str
    def execute(self, action: dict, *, context: ActionContext) -> ActionResult: ...

_registry: dict[str, ActionHandler] = {}

def register(handler: ActionHandler) -> None:
    _registry[handler.action_type] = handler
```

The `execute_actions()` function becomes a loop:

```python
for action in actions:
    handler = _registry.get(action.get("type"))
    if handler is None:
        results.append(ActionResult(ok=False, error="unsupported_action"))
        continue
    results.append(handler.execute(action, context=ctx))
```

Each handler lives in its own module (e.g., `action_handlers/alarm_disarm.py`) and is registered at import time. New action types are added by creating a new handler file — no modification to the executor.

---

#### Finding 12 — Move serializer logic to `alarm/use_cases/rules.py`

Extract `create_rule()` and `update_rule()` use cases:

```python
# alarm/use_cases/rules.py
def create_rule(*, validated_data: dict, entity_ids: list[str] | None) -> Rule:
    """Orchestrate rule creation: derive kind, extract entities, persist, invalidate cache."""
    ...

def update_rule(*, rule: Rule, validated_data: dict, entity_ids: list[str] | None) -> Rule:
    """Orchestrate rule update: derive kind, extract entities, persist, invalidate cache."""
    ...
```

The serializer's `create()` and `update()` become one-liners that delegate to these use cases. The inline imports move to the use-case module where they belong, eliminating the circular-import workaround.

---

#### Finding 13 — Extract `IntegrationOutageTracker` class

Encapsulate the mutable state from `receivers.py` into a class:

```python
class IntegrationOutageTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._offline_since: dict[str, datetime] = {}
        self._event_emitted: set[str] = set()

    def mark_offline(self, integration: str, now: datetime) -> None: ...
    def mark_online(self, integration: str, now: datetime) -> float | None: ...
    def check_prolonged(self, integration: str, checked_at: datetime) -> bool: ...
```

Benefits: explicit thread safety via `threading.Lock()`, testable without monkeypatching module globals, resettable between tests via a new instance.

---

#### Finding 14 — Narrow exception handling (prioritized audit)

Audit the 258 `except Exception` sites in priority order:

| Priority | Scope | Count | Approach |
|----------|-------|-------|----------|
| Critical | `scheduler/runner.py` silent passes | 8 | Replace `pass` with `logger.debug()`; extract `_safe_telemetry()` |
| Critical | `alarm/dispatcher/dispatcher.py` | 2 | Catch `DomainError \| GatewayError` explicitly |
| High | `alarm/rules/conditions.py` | 14 | Catch `(TypeError, ValueError, KeyError)` for data coercion; catch `GatewayError` for repo calls |
| High | `alarm/rules/action_executor.py` | 9 | Already captures `exc` for structured errors; narrow to `GatewayError \| DomainError \| OSError` |
| Medium | `notifications/dispatcher.py` | 2 | Logging failures — keep broad but add `logger.debug()` |
| Medium | `integrations_*/runtime.py` | 25 | Network/transport errors — narrow to `OSError \| GatewayError` |
| Low | `scheduler/telemetry.py` | 7 | Telemetry helpers — add DEBUG logging |

---

#### Finding 15 — Dependency injection for gateway singletons

Replace module-level singleton defaults with explicit passing:

**Current pattern (26 files):**
```python
from alarm.gateways.home_assistant import default_home_assistant_gateway

class SomeView(APIView):
    def get(self, request):
        result = default_home_assistant_gateway.call_service(...)
```

**Recommended pattern:**
```python
class SomeView(APIView):
    def get(self, request, ha_gateway=None):
        gateway = ha_gateway or get_home_assistant_gateway()
        result = gateway.call_service(...)
```

Or via a lightweight DI container / request-scoped factory. This aligns with ADR 0009's intent and makes views unit-testable without monkeypatching module-level objects.

---

## Consequences

### Positive

- **Extensibility:** Strategy/registry pattern enables new action types without modifying the executor (OCP)
- **Thin serializers:** Moving logic to use cases restores ADR 0005 compliance and eliminates circular-import workarounds
- **Visible exceptions:** Replacing silent `pass` blocks with logging ensures broken telemetry/helpers are detectable
- **Testability:** Extracting `IntegrationOutageTracker` and using DI for gateways enables unit testing without monkeypatching

### Negative

- **Strategy pattern adds indirection:** Developers must find the handler file for a given action type instead of reading one function
- **Serializer migration touches hot path:** `create_rule()` / `update_rule()` extraction must be done carefully to avoid regressions in rule CRUD
- **Narrowing exceptions is labor-intensive:** 258 sites require individual analysis of which exceptions are expected vs. bugs

### Neutral

- Most findings are **drift from patterns already established** in ADRs 0005/0006/0009, not new architectural decisions
- The codebase is functional and well-tested; these are maintainability and extensibility improvements, not correctness fixes

---

## Todos

### Critical

- [ ] Replace the 48 `except Exception: pass` sites with minimum `logger.debug()` logging
- [ ] Add structured logging to `action_executor.py` catch blocks (already captures `exc`; add `logger.warning()`)
- [ ] Add `threading.Lock()` to `receivers.py` outage state (or extract `IntegrationOutageTracker`)

### High

- [ ] Implement action handler registry pattern (Finding 11) — extract 9 handlers from `action_executor.py`
- [ ] Extract `create_rule()` / `update_rule()` use cases from `serializers/rules.py` (Finding 12)
- [ ] Extract `IntegrationOutageTracker` class from `receivers.py` (Finding 13)
- [ ] Remove HA system provider special-casing from `notifications/dispatcher.py` (Finding 6)

### Medium

- [ ] Narrow `except Exception` in `alarm/dispatcher/dispatcher.py` to `DomainError | GatewayError`
- [ ] Narrow `except Exception` in `alarm/rules/conditions.py` to `(TypeError, ValueError, KeyError)` + `GatewayError`
- [ ] Extract `SuspendedRulesView` ORM queries into a use case (ADR 0005 compliance)
- [ ] Replace `default_*_gateway` singleton imports in views with explicit DI (Finding 15)

### Low

- [ ] Split `AlarmServices` protocol into `AlarmSnapshotService` + `AlarmCommandService` (Finding 9)
- [ ] Audit `integrations_zigbee2mqtt/runtime.py` catches (8 silent passes)
- [ ] Audit `integrations_home_assistant/state_stream.py` catches (3 silent passes)
- [ ] Document action handler registration pattern in developer guide

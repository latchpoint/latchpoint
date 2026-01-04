# ADR-0046: Home Assistant WebSocket State Subscription

## Status
Superseded by ADR 0057

## Context

### Current Architecture

Home Assistant entity states are synced via polling:

```
┌─────────────────┐     REST API      ┌─────────────────┐
│  sync_entity_   │ ───────────────▶  │  Home Assistant │
│  states task    │   every 5 min     │                 │
│  (alarm/tasks)  │ ◀───────────────  │                 │
└─────────────────┘   entity list     └─────────────────┘
        │
        ▼
   Update Entity
   records in DB
        │
        ▼
   Broadcast to UI
   (WebSocket)
        │
        ✗ NO rules triggered
```

### Problem

1. **5-minute latency**: A door opening won't trigger rules until the next sync cycle
2. **Rules never fire**: `sync_entity_states` updates Entity records but does NOT call `run_rules()`
3. **Inconsistent behavior**: Zigbee2MQTT and Frigate trigger rules in real-time via MQTT, but HA entities don't
4. **Wasted API calls**: Polling fetches ALL entities even when nothing changed

### Real-Time Comparison

| Integration | State Update | Triggers Rules | Latency |
|-------------|--------------|----------------|---------|
| Zigbee2MQTT | MQTT subscription | Yes | <100ms |
| Frigate | MQTT subscription | Yes | <100ms |
| Home Assistant | REST polling | **No** | **~5 min** |

### Example Failure Scenario

```
Rule: IF backdoor.state == "open" AND alarm.state == "armed_away" THEN trigger

Timeline:
- 00:00 - Alarm armed away
- 00:01 - Backdoor opens (HA entity state changes)
- 00:01 - sync_entity_states last ran 4 minutes ago
- 00:05 - Next sync runs, updates Entity.last_state to "open"
- 00:05 - Rules NOT evaluated, alarm does NOT trigger
- Intruder has 5+ minutes before any response
```

## Decision

Replace REST polling with Home Assistant WebSocket API subscription for real-time state change events, and trigger rules when tracked entities change state.

### Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  integrations_home_assistant                 │
│  ┌─────────────┐                    ┌─────────────────────┐ │
│  │  WebSocket  │   state_changed    │  _on_state_changed  │ │
│  │  Connection │ ─────────────────▶ │  handler            │ │
│  │  Manager    │   (real-time)      │                     │ │
│  └─────────────┘                    └─────────────────────┘ │
│         │                                    │              │
│         │ subscribe_events                   ▼              │
│         │ (state_changed)            Update Entity          │
│         │                                    │              │
└─────────┼────────────────────────────────────┼──────────────┘
          │                                    │
          ▼                                    ▼
   ┌─────────────────┐               ┌─────────────────┐
   │ Home Assistant  │               │  rules_engine.  │
   │ WebSocket API   │               │  run_rules()    │
   │ /api/websocket  │               │  (debounced)    │
   └─────────────────┘               └─────────────────┘
```

### Implementation

#### 1. WebSocket Connection Manager

```python
# backend/integrations_home_assistant/websocket_manager.py

import asyncio
import json
import logging
import threading
from typing import Callable

import websockets
from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)

_CACHE_KEY_LAST_RULES_RUN_AT = "ha_ws:last_rules_run_at"
_CACHE_KEY_RULES_RUNS_PER_MINUTE = "ha_ws:rules_runs_per_minute"


class HomeAssistantWebSocketManager:
    """Manages a persistent WebSocket connection to Home Assistant."""

    def __init__(self):
        self._ws = None
        self._loop = None
        self._thread = None
        self._running = False
        self._message_id = 0
        self._subscribed = False
        self._on_state_changed: Callable | None = None

    def start(self, *, base_url: str, token: str, on_state_changed: Callable) -> None:
        """Start the WebSocket connection in a background thread."""
        if self._running:
            return

        self._on_state_changed = on_state_changed
        ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url.rstrip('/')}/api/websocket"

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(ws_url, token),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run_loop(self, ws_url: str, token: str) -> None:
        """Background thread event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_loop(ws_url, token))
        except Exception as e:
            logger.error("HA WebSocket loop error: %s", e)
        finally:
            self._loop.close()

    async def _connect_loop(self, ws_url: str, token: str) -> None:
        """Reconnecting connection loop."""
        while self._running:
            try:
                await self._connect(ws_url, token)
            except Exception as e:
                logger.warning("HA WebSocket connection failed: %s, retrying in 10s", e)
                await asyncio.sleep(10)

    async def _connect(self, ws_url: str, token: str) -> None:
        """Establish connection, authenticate, and subscribe to events."""
        async with websockets.connect(ws_url) as ws:
            self._ws = ws
            self._subscribed = False

            # Wait for auth_required
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_required":
                raise RuntimeError(f"Unexpected message: {msg}")

            # Authenticate
            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_ok":
                raise RuntimeError(f"Auth failed: {msg}")

            logger.info("HA WebSocket authenticated")

            # Subscribe to state_changed events
            self._message_id += 1
            await ws.send(json.dumps({
                "id": self._message_id,
                "type": "subscribe_events",
                "event_type": "state_changed",
            }))
            self._subscribed = True
            logger.info("HA WebSocket subscribed to state_changed events")

            # Message loop
            async for raw in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw)
                    if msg.get("type") == "event" and msg.get("event", {}).get("event_type") == "state_changed":
                        self._handle_state_changed(msg["event"]["data"])
                except Exception as e:
                    logger.warning("HA WebSocket message error: %s", e)

    def _handle_state_changed(self, data: dict) -> None:
        """Process a state_changed event."""
        close_old_connections()
        entity_id = data.get("entity_id")
        new_state = data.get("new_state") or {}
        old_state = data.get("old_state") or {}

        if self._on_state_changed:
            try:
                self._on_state_changed(
                    entity_id=entity_id,
                    old_state=old_state.get("state"),
                    new_state=new_state.get("state"),
                    attributes=new_state.get("attributes", {}),
                )
            except Exception as e:
                logger.warning("HA state_changed handler error: %s", e)


ha_websocket_manager = HomeAssistantWebSocketManager()
```

#### 2. Runtime Integration

```python
# backend/integrations_home_assistant/runtime.py

import logging
import threading
from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from alarm.models import Entity
from integrations_home_assistant.websocket_manager import ha_websocket_manager

logger = logging.getLogger(__name__)

_CACHE_KEY_LAST_RULES_RUN_AT = "ha_ws:last_rules_run_at"
_CACHE_KEY_RULES_RUNS_PER_MINUTE = "ha_ws:rules_runs_per_minute"

_init_lock = threading.Lock()
_initialized = False


def get_settings() -> dict:
    """Read HA WebSocket settings from active profile."""
    from alarm.state_machine.settings import get_active_settings_profile, get_setting_json
    profile = get_active_settings_profile()
    raw = get_setting_json(profile, "home_assistant_connection") or {}
    return {
        "enabled": bool(raw.get("enabled")),
        "base_url": str(raw.get("base_url") or "").strip(),
        "token": str(raw.get("token") or "").strip(),
        "run_rules_on_event": bool(raw.get("run_rules_on_event", True)),
        "run_rules_debounce_seconds": int(raw.get("run_rules_debounce_seconds") or 2),
        "run_rules_max_per_minute": int(raw.get("run_rules_max_per_minute") or 60),
        "run_rules_kinds": list(raw.get("run_rules_kinds") or ["trigger"]),
    }


def initialize() -> None:
    """Start the WebSocket connection if configured."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

    settings = get_settings()
    if not settings["enabled"] or not settings["base_url"] or not settings["token"]:
        return

    from alarm.crypto import decrypt_secret
    token = decrypt_secret(settings["token"])

    ha_websocket_manager.start(
        base_url=settings["base_url"],
        token=token,
        on_state_changed=_on_state_changed,
    )


def _on_state_changed(
    *,
    entity_id: str,
    old_state: str | None,
    new_state: str | None,
    attributes: dict,
) -> None:
    """Handle a state_changed event from Home Assistant."""
    close_old_connections()
    now = timezone.now()

    # Update Entity record if it exists
    updated = Entity.objects.filter(
        entity_id=entity_id,
        source="home_assistant",
    ).update(
        last_state=new_state,
        last_changed=now,
        last_seen=now,
    )

    if updated == 0:
        # Entity not tracked, skip rules
        return

    if old_state == new_state:
        # State didn't actually change
        return

    logger.info(
        "HA entity %s state changed: %s -> %s",
        entity_id,
        old_state,
        new_state,
    )

    # Broadcast to UI
    try:
        from alarm.websocket import broadcast_entity_sync
        broadcast_entity_sync(entities=[{
            "entity_id": entity_id,
            "old_state": old_state,
            "new_state": new_state,
        }])
    except Exception:
        pass

    # Trigger rules evaluation
    _maybe_trigger_rules_run()


def _maybe_trigger_rules_run() -> None:
    """Run rules with debounce and rate limiting."""
    settings = get_settings()
    if not settings.get("run_rules_on_event"):
        return

    debounce = int(settings.get("run_rules_debounce_seconds") or 0)
    now = timezone.now()

    if debounce:
        last = cache.get(_CACHE_KEY_LAST_RULES_RUN_AT)
        if isinstance(last, str):
            try:
                last_dt = timezone.datetime.fromisoformat(last)
                if timezone.is_naive(last_dt):
                    last_dt = timezone.make_aware(last_dt)
                if now - last_dt < timezone.timedelta(seconds=debounce):
                    return
            except Exception:
                pass
        cache.set(_CACHE_KEY_LAST_RULES_RUN_AT, now.isoformat(), timeout=None)

    max_per_min = int(settings.get("run_rules_max_per_minute") or 0)
    if max_per_min > 0:
        current = cache.get(_CACHE_KEY_RULES_RUNS_PER_MINUTE) or 0
        if current >= max_per_min:
            return
        cache.set(_CACHE_KEY_RULES_RUNS_PER_MINUTE, current + 1, timeout=60)

    def _run() -> None:
        close_old_connections()
        try:
            from alarm import rules_engine
            from alarm.rules.repositories import RuleEngineRepositories, default_rule_engine_repositories

            repos = default_rule_engine_repositories()
            allowed_kinds = set(settings.get("run_rules_kinds") or [])
            if allowed_kinds:
                original = repos

                def _list_filtered():
                    return [r for r in original.list_enabled_rules() if getattr(r, "kind", None) in allowed_kinds]

                repos = RuleEngineRepositories(
                    list_enabled_rules=_list_filtered,
                    entity_state_map=original.entity_state_map,
                    due_runtimes=original.due_runtimes,
                    ensure_runtime=original.ensure_runtime,
                    frigate_is_available=original.frigate_is_available,
                    list_frigate_detections=original.list_frigate_detections,
                    get_alarm_state=original.get_alarm_state,
                )

            rules_engine.run_rules(actor_user=None, repos=repos)
        except Exception as e:
            logger.warning("Failed to run rules on HA state change: %s", e)

    threading.Thread(target=_run, daemon=True).start()
```

#### 3. Settings Schema Update

Add to `home_assistant_connection` settings:

```python
{
    "enabled": True,
    "base_url": "http://homeassistant.local:8123",
    "token": "encrypted:...",
    "connect_timeout_seconds": 2,
    # New fields:
    "run_rules_on_event": True,           # Enable rules triggering
    "run_rules_debounce_seconds": 2,      # Min interval between rule runs
    "run_rules_max_per_minute": 60,       # Rate limit
    "run_rules_kinds": ["trigger"],       # Rule kinds to evaluate
}
```

#### 4. Remove Polling Task

The `sync_entity_states` scheduled task becomes redundant and can be removed or converted to a fallback-only mechanism.

```python
# Option A: Remove entirely
# Delete sync_entity_states from alarm/tasks.py

# Option B: Keep as fallback with longer interval
@register("sync_entity_states_fallback", schedule=DailyAt(hour=3, minute=15))
def sync_entity_states_fallback() -> dict:
    """Fallback daily sync for entities that may have been missed."""
    # ... existing logic ...
```

### Connection Lifecycle

```
App Start
    │
    ▼
apps.py ready()
    │
    ▼
runtime.initialize()
    │
    ├──▶ Settings disabled? → Skip
    │
    ▼
ha_websocket_manager.start()
    │
    ▼
Background Thread
    │
    ├──▶ Connect to ws://ha:8123/api/websocket
    ├──▶ Authenticate with token
    ├──▶ Subscribe to state_changed
    │
    ▼
Event Loop (reconnects on failure)
    │
    ├──▶ state_changed event received
    ├──▶ _on_state_changed()
    ├──▶ Update Entity
    ├──▶ Broadcast to UI
    └──▶ _maybe_trigger_rules_run()
```

## Alternatives Considered

### 1. Keep Polling, Add Rules Trigger

```python
# In sync_entity_states:
if updated > 0:
    rules_engine.run_rules(actor_user=None)
```

- **Pros**: Minimal change
- **Cons**: Still 5-minute latency; defeats the purpose
- **Verdict**: Rejected - doesn't solve the core problem

### 2. Shorter Polling Interval (e.g., 10 seconds)

- **Pros**: Simpler than WebSocket
- **Cons**: Hammers HA API; wastes bandwidth; still has latency
- **Verdict**: Rejected - inefficient and still not real-time

### 3. HA Automation Webhook

Configure HA automations to POST to our API on state changes.

- **Pros**: Uses HA's event system
- **Cons**: Requires HA configuration; harder to set up; callback URL exposure
- **Verdict**: Rejected - shifts complexity to user

### 4. MQTT State Topic (via HA MQTT integration)

Have HA publish state changes to MQTT, subscribe via existing MQTT transport.

- **Pros**: Reuses existing MQTT infrastructure
- **Cons**: Requires HA MQTT addon; non-standard setup
- **Verdict**: Future consideration for users with MQTT already

## Consequences

### Positive

- **Real-time response**: <100ms latency for HA entity state changes
- **Rules triggered immediately**: Backdoor opens → alarm triggers instantly
- **Reduced API load**: No more polling; only receive actual changes
- **Consistent behavior**: HA entities now behave like Z2M/Frigate
- **Battery-friendly**: No constant polling wake-ups

### Negative

- **WebSocket dependency**: Requires persistent connection; must handle reconnects
- **Token exposure**: Long-lived token used for WebSocket (same as REST)
- **Complexity**: WebSocket lifecycle management vs simple HTTP calls
- **HA version dependency**: WebSocket API has been stable since HA 0.107+

### Mitigations

- Automatic reconnection with exponential backoff
- Connection health monitoring via existing status system
- Graceful degradation if WebSocket fails (log warning, don't crash)
- Optional fallback daily sync for missed events

## Migration Path

1. Add `websockets` to `requirements.txt`
2. Create `integrations_home_assistant/websocket_manager.py`
3. Create `integrations_home_assistant/runtime.py`
4. Update `integrations_home_assistant/apps.py` to call `runtime.initialize()`
5. Add new settings fields to `home_assistant_connection` schema
6. Update Settings UI to expose new options
7. Test with real HA instance
8. Remove or reduce `sync_entity_states` task
9. Update ADR 0027 to reference this ADR

## Todos

### Phase 1 (Core)
- [ ] Add `websockets` dependency to requirements.txt
- [ ] Implement `websocket_manager.py` with connection lifecycle
- [ ] Implement `runtime.py` with state change handler
- [ ] Wire up initialization in `apps.py`
- [ ] Add settings schema fields for rules triggering config
- [ ] Test WebSocket connection and event handling

### Phase 2 (Rules Integration)
- [ ] Implement `_maybe_trigger_rules_run()` with debounce/rate limiting
- [ ] Test end-to-end: HA state change → Entity update → Rules fire
- [ ] Add cache counters for observability

### Phase 3 (Cleanup)
- [ ] Remove or reduce `sync_entity_states` polling task
- [ ] Update Settings UI for new HA connection options
- [ ] Add WebSocket connection status to system status endpoint
- [ ] Update ADR 0027 status to Superseded by 0046

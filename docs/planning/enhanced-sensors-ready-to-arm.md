# Enhanced Sensors & Ready-to-Arm Planning Document

**Status:** Draft
**Priority:** High
**Estimated Scope:** Medium

## Overview

This document outlines the implementation plan for two tightly-coupled features:

1. **Enhanced Sensor Model** - Add Alarmo-style sensor behaviors (always_on, use_exit_delay, per-sensor entry delay, etc.)
2. **Ready-to-Arm Status** - Real-time feedback on which arm modes are available based on sensor states

These features transform the alarm from a basic panel into a smart security system with behavior users expect from professional alarm systems.

---

## Current State

### Sensor Model (Today)

```python
class Sensor(models.Model):
    name = models.CharField(max_length=150)
    entity_id = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_entry_point = models.BooleanField(default=False)
```

### Current Behavior

| Scenario | Behavior |
|----------|----------|
| Any sensor triggers while armed | Entry point → PENDING, otherwise → TRIGGERED |
| Sensor open during arming | Ignored (arms anyway) |
| Smoke detector triggers while disarmed | Ignored |
| Sensor becomes unavailable | Ignored |
| Motion sensor during exit delay | Could abort arming (unintended) |

### Problems

1. **No sensor types** - Motion sensors behave like door sensors
2. **No always-on sensors** - Smoke/CO detectors should trigger even when disarmed
3. **No exit delay awareness** - Motion sensors trip during exit countdown
4. **No open sensor handling** - System arms with doors open (security risk)
5. **No per-sensor timing** - All entry points use same delay
6. **No user feedback** - Users don't know why arming fails

---

## Target State

### Enhanced Sensor Model

```python
class SensorType(models.TextChoices):
    DOOR = "door", "Door"
    WINDOW = "window", "Window"
    MOTION = "motion", "Motion"
    TAMPER = "tamper", "Tamper"
    ENVIRONMENTAL = "environmental", "Environmental"  # smoke, CO, water
    OTHER = "other", "Other"


class Sensor(models.Model):
    # Existing fields
    name = models.CharField(max_length=150)
    entity_id = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    # Renamed for clarity
    is_entry_point = models.BooleanField(default=False)  # DEPRECATED, keep for migration

    # NEW: Sensor classification
    sensor_type = models.CharField(
        max_length=20,
        choices=SensorType.choices,
        default=SensorType.OTHER,
    )

    # NEW: Behavior flags
    always_on = models.BooleanField(
        default=False,
        help_text="Trigger alarm even when disarmed (smoke/CO detectors)",
    )
    use_exit_delay = models.BooleanField(
        default=True,
        help_text="Allow sensor to be open during exit countdown",
    )
    use_entry_delay = models.BooleanField(
        default=True,
        help_text="Use entry delay vs instant trigger when tripped",
    )
    entry_delay_override = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Per-sensor entry delay in seconds (null = use system default)",
    )

    # NEW: Arming behavior
    allow_open = models.BooleanField(
        default=False,
        help_text="Sensor can be open when arming (garage door scenario)",
    )
    auto_bypass = models.BooleanField(
        default=False,
        help_text="Auto-bypass if open when arming",
    )
    arm_on_close = models.BooleanField(
        default=False,
        help_text="Wait for sensor to close before completing arm",
    )

    # NEW: Reliability
    trigger_unavailable = models.BooleanField(
        default=False,
        help_text="Trigger alarm if sensor becomes unavailable",
    )

    # NEW: Mode filtering
    enabled_modes = models.JSONField(
        default=list,
        blank=True,
        help_text="Arm modes where sensor is active. Empty = all modes.",
    )
```

### Behavior Matrix

| Flag | Effect |
|------|--------|
| `always_on=True` | Triggers in ANY state including disarmed |
| `use_exit_delay=False` | Tripping during ARMING aborts the arm |
| `use_entry_delay=False` | Instant TRIGGERED (no PENDING state) |
| `entry_delay_override=30` | 30s entry delay instead of system default |
| `allow_open=True` | Can arm even if sensor is open |
| `auto_bypass=True` | Automatically bypass if open when arming |
| `arm_on_close=True` | Arming waits for sensor to close |
| `trigger_unavailable=True` | Unavailable state = trigger |
| `enabled_modes=["armed_away"]` | Only active in away mode |

### Smart Defaults by Sensor Type

| Type | always_on | use_exit_delay | use_entry_delay | Rationale |
|------|-----------|----------------|-----------------|-----------|
| door | False | True | True | Entry points with delays |
| window | False | True | False | Instant trigger |
| motion | False | True | False | Ignore during exit, instant trigger |
| tamper | True | False | False | Always instant |
| environmental | True | False | False | Always instant (smoke/CO) |
| other | False | True | True | Conservative default |

---

## Ready-to-Arm Status

### New Endpoint

```
GET /api/alarm/ready-to-arm/
```

### Response Schema

```typescript
interface ReadyToArmResponse {
  modes: {
    [mode: string]: {
      ready: boolean
      blocking_sensors: BlockingSensor[]
      bypassable_sensors: BypassableSensor[]
    }
  }
  global_issues: string[]  // e.g., "Home Assistant unavailable"
}

interface BlockingSensor {
  id: number
  name: string
  entity_id: string
  current_state: 'open' | 'unavailable'
  reason: 'open' | 'unavailable'
}

interface BypassableSensor {
  id: number
  name: string
  entity_id: string
  auto_bypass: boolean  // Will be auto-bypassed if arming proceeds
}
```

### Example Response

```json
{
  "modes": {
    "armed_away": {
      "ready": false,
      "blocking_sensors": [
        {
          "id": 1,
          "name": "Front Door",
          "entity_id": "binary_sensor.front_door",
          "current_state": "open",
          "reason": "open"
        }
      ],
      "bypassable_sensors": []
    },
    "armed_home": {
      "ready": true,
      "blocking_sensors": [],
      "bypassable_sensors": []
    },
    "armed_night": {
      "ready": true,
      "blocking_sensors": [],
      "bypassable_sensors": []
    },
    "armed_vacation": {
      "ready": false,
      "blocking_sensors": [
        {
          "id": 1,
          "name": "Front Door",
          "entity_id": "binary_sensor.front_door",
          "current_state": "open",
          "reason": "open"
        }
      ],
      "bypassable_sensors": []
    }
  },
  "global_issues": []
}
```

### WebSocket Events

Push ready-to-arm updates when sensor states change:

```typescript
// New WebSocket message type
{
  "type": "ready_to_arm_changed",
  "payload": ReadyToArmResponse
}
```

---

## Implementation Plan

### Phase 1A: Database Migration

**File:** `backend/alarm/migrations/XXXX_enhanced_sensor_model.py`

```python
from django.db import migrations, models


def set_smart_defaults(apps, schema_editor):
    """Set defaults based on existing is_entry_point flag."""
    Sensor = apps.get_model('alarm', 'Sensor')

    # Entry points get entry delay
    Sensor.objects.filter(is_entry_point=True).update(
        use_entry_delay=True,
        sensor_type='door',
    )

    # Non-entry points = instant trigger (likely motion/window)
    Sensor.objects.filter(is_entry_point=False).update(
        use_entry_delay=False,
        sensor_type='motion',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('alarm', 'XXXX_previous'),
    ]

    operations = [
        # Add new fields
        migrations.AddField(
            model_name='sensor',
            name='sensor_type',
            field=models.CharField(
                choices=[
                    ('door', 'Door'),
                    ('window', 'Window'),
                    ('motion', 'Motion'),
                    ('tamper', 'Tamper'),
                    ('environmental', 'Environmental'),
                    ('other', 'Other'),
                ],
                default='other',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='sensor',
            name='always_on',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='sensor',
            name='use_exit_delay',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='sensor',
            name='use_entry_delay',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='sensor',
            name='entry_delay_override',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='sensor',
            name='allow_open',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='sensor',
            name='auto_bypass',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='sensor',
            name='arm_on_close',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='sensor',
            name='trigger_unavailable',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='sensor',
            name='enabled_modes',
            field=models.JSONField(blank=True, default=list),
        ),

        # Run data migration
        migrations.RunPython(set_smart_defaults, migrations.RunPython.noop),
    ]
```

### Phase 1B: Model Update

**File:** `backend/alarm/models.py`

Add the new fields and choices to the Sensor model as specified above.

Add helper methods:

```python
class Sensor(models.Model):
    # ... fields ...

    def is_active_for_mode(self, arm_mode: str) -> bool:
        """Check if sensor is active for the given arm mode."""
        if not self.is_active:
            return False
        if not self.enabled_modes:
            return True  # Empty = all modes
        return arm_mode in self.enabled_modes

    def get_entry_delay(self, system_delay: int) -> int:
        """Get entry delay for this sensor."""
        if not self.use_entry_delay:
            return 0
        if self.entry_delay_override is not None:
            return self.entry_delay_override
        return system_delay

    def should_block_arming(self, current_state: str) -> bool:
        """Check if sensor should block arming."""
        if self.allow_open:
            return False
        if self.auto_bypass:
            return False  # Will be bypassed, not blocked
        return current_state == "open"

    def should_auto_bypass(self, current_state: str) -> bool:
        """Check if sensor should be auto-bypassed."""
        return self.auto_bypass and current_state == "open"
```

### Phase 1C: State Machine Updates

**File:** `backend/alarm/state_machine/transitions.py`

#### Update `sensor_triggered()`:

```python
@transaction.atomic
def sensor_triggered(
    *,
    sensor: Sensor,
    user=None,
    reason: str = "sensor_triggered",
) -> AlarmStateSnapshot:
    snapshot = get_snapshot_for_update()
    now = timezone.now()
    record_sensor_event(sensor, timestamp=now)

    # NEW: Always-on sensors trigger even when disarmed
    if sensor.always_on and snapshot.current_state == AlarmState.DISARMED:
        timing = timing_from_snapshot(snapshot)
        exit_at = now + timedelta(seconds=timing.trigger_time)
        return transition(
            snapshot=snapshot,
            state_to=AlarmState.TRIGGERED,
            now=now,
            user=user,
            reason="always_on_sensor",
            exit_at=exit_at,
            sensor=sensor,
        )

    # Ignore if already pending or triggered
    if snapshot.current_state in {AlarmState.PENDING, AlarmState.TRIGGERED}:
        return snapshot

    # NEW: Handle ARMING state
    if snapshot.current_state == AlarmState.ARMING:
        if not sensor.use_exit_delay:
            # Sensor without exit delay = abort arming
            return cancel_arming(reason="sensor_triggered_no_exit_delay")
        # Sensor with exit delay = ignore during arming
        return snapshot

    # Ignore if not in armed states
    if snapshot.current_state not in ARMED_STATES:
        return snapshot

    # NEW: Check if sensor is active for current mode
    current_mode = snapshot.current_state.value  # e.g., "armed_away"
    if not sensor.is_active_for_mode(current_mode):
        return snapshot

    set_previous_armed_state(snapshot)
    snapshot.save(update_fields=["previous_state"])
    timing = timing_from_snapshot(snapshot)

    # NEW: Use per-sensor entry delay
    if sensor.use_entry_delay:
        entry_delay = sensor.get_entry_delay(timing.delay_time)
        snapshot.timing_snapshot = timing.as_dict()
        snapshot.save(update_fields=["timing_snapshot"])
        exit_at = now + timedelta(seconds=entry_delay)
        return transition(
            snapshot=snapshot,
            state_to=AlarmState.PENDING,
            now=now,
            user=user,
            reason=reason,
            exit_at=exit_at,
            update_previous=False,
            sensor=sensor,
        )

    # Instant trigger
    exit_at = now + timedelta(seconds=timing.trigger_time)
    return transition(
        snapshot=snapshot,
        state_to=AlarmState.TRIGGERED,
        now=now,
        user=user,
        reason=reason,
        exit_at=exit_at,
        update_previous=False,
        sensor=sensor,
    )
```

#### New function: `validate_arming()`:

```python
@dataclass
class ArmingValidation:
    can_arm: bool
    blocking_sensors: list[Sensor]
    bypass_sensors: list[Sensor]
    wait_for_close_sensors: list[Sensor]


def validate_arming(
    *,
    target_mode: str,
    sensor_states: dict[int, str],  # sensor_id -> "open"|"closed"|"unknown"
) -> ArmingValidation:
    """
    Validate if arming can proceed for the given mode.

    Returns which sensors block, should be bypassed, or need to close.
    """
    sensors = Sensor.objects.filter(is_active=True)

    blocking = []
    bypass = []
    wait_for_close = []

    for sensor in sensors:
        if not sensor.is_active_for_mode(target_mode):
            continue

        state = sensor_states.get(sensor.id, "unknown")

        if state != "open":
            continue

        if sensor.allow_open:
            continue

        if sensor.auto_bypass:
            bypass.append(sensor)
            continue

        if sensor.arm_on_close:
            wait_for_close.append(sensor)
            continue

        # Sensor blocks arming
        blocking.append(sensor)

    can_arm = len(blocking) == 0 and len(wait_for_close) == 0

    return ArmingValidation(
        can_arm=can_arm,
        blocking_sensors=blocking,
        bypass_sensors=bypass,
        wait_for_close_sensors=wait_for_close,
    )
```

### Phase 1D: Serializer Updates

**File:** `backend/alarm/serializers/sensors.py`

```python
class SensorSerializer(serializers.ModelSerializer):
    entity_id = serializers.CharField(allow_blank=True, required=False)
    current_state = serializers.SerializerMethodField()
    last_triggered = serializers.SerializerMethodField()
    used_in_rules = serializers.SerializerMethodField()

    class Meta:
        model = Sensor
        fields = (
            "id",
            "name",
            "entity_id",
            "is_active",
            # NEW fields
            "sensor_type",
            "always_on",
            "use_exit_delay",
            "use_entry_delay",
            "entry_delay_override",
            "allow_open",
            "auto_bypass",
            "arm_on_close",
            "trigger_unavailable",
            "enabled_modes",
            # Computed fields
            "current_state",
            "last_triggered",
            "used_in_rules",
            # DEPRECATED but keep for compatibility
            "is_entry_point",
        )


class SensorCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sensor
        fields = (
            "id",
            "name",
            "entity_id",
            "is_active",
            "sensor_type",
            "always_on",
            "use_exit_delay",
            "use_entry_delay",
            "entry_delay_override",
            "allow_open",
            "auto_bypass",
            "arm_on_close",
            "trigger_unavailable",
            "enabled_modes",
        )

    def validate_entity_id(self, value: str) -> str:
        entity_id = (value or "").strip()
        if not entity_id:
            raise serializers.ValidationError("entity_id is required.")
        if "." not in entity_id:
            raise serializers.ValidationError("Invalid entity_id.")
        return entity_id

    def validate_enabled_modes(self, value: list) -> list:
        valid_modes = {"armed_away", "armed_home", "armed_night", "armed_vacation"}
        for mode in value:
            if mode not in valid_modes:
                raise serializers.ValidationError(f"Invalid mode: {mode}")
        return value


class SensorUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sensor
        fields = (
            "id",
            "name",
            "is_active",
            "sensor_type",
            "always_on",
            "use_exit_delay",
            "use_entry_delay",
            "entry_delay_override",
            "allow_open",
            "auto_bypass",
            "arm_on_close",
            "trigger_unavailable",
            "enabled_modes",
        )
```

### Phase 2A: Ready-to-Arm Use Case

**File:** `backend/alarm/use_cases/ready_to_arm.py`

```python
from dataclasses import dataclass
from typing import Protocol

from alarm.models import Sensor
from alarm.gateways.home_assistant import HomeAssistantGateway, default_home_assistant_gateway
from alarm.domain.entity_state import normalize_contact_state


@dataclass
class BlockingSensor:
    id: int
    name: str
    entity_id: str
    current_state: str
    reason: str  # "open" or "unavailable"


@dataclass
class BypassableSensor:
    id: int
    name: str
    entity_id: str
    auto_bypass: bool


@dataclass
class ModeReadiness:
    ready: bool
    blocking_sensors: list[BlockingSensor]
    bypassable_sensors: list[BypassableSensor]


@dataclass
class ReadyToArmResult:
    modes: dict[str, ModeReadiness]
    global_issues: list[str]


ARM_MODES = ["armed_away", "armed_home", "armed_night", "armed_vacation"]


def get_ready_to_arm_status(
    *,
    ha_gateway: HomeAssistantGateway = default_home_assistant_gateway,
) -> ReadyToArmResult:
    """
    Calculate which arm modes are ready based on current sensor states.
    """
    global_issues = []

    # Get all active sensors
    sensors = list(Sensor.objects.filter(is_active=True))

    # Get entity states
    entity_ids = {s.entity_id for s in sensors if s.entity_id}
    entity_states = {}

    try:
        ha_entities = ha_gateway.list_entities()
        for entity in ha_entities:
            if entity.entity_id in entity_ids:
                entity_states[entity.entity_id] = entity.state
    except Exception:
        global_issues.append("Home Assistant unavailable - using cached states")
        # Fall back to database states
        from alarm.models import Entity
        for entity in Entity.objects.filter(entity_id__in=entity_ids):
            entity_states[entity.entity_id] = entity.last_state

    # Calculate readiness per mode
    modes = {}
    for mode in ARM_MODES:
        blocking = []
        bypassable = []

        for sensor in sensors:
            # Skip if sensor not active for this mode
            if not sensor.is_active_for_mode(mode):
                continue

            # Get current state
            raw_state = entity_states.get(sensor.entity_id)
            state = normalize_contact_state(raw_state)

            # Check unavailable
            if state == "unknown" and sensor.trigger_unavailable:
                blocking.append(BlockingSensor(
                    id=sensor.id,
                    name=sensor.name,
                    entity_id=sensor.entity_id,
                    current_state="unavailable",
                    reason="unavailable",
                ))
                continue

            # Check open
            if state != "open":
                continue

            # Sensor is open - check behavior flags
            if sensor.allow_open:
                continue

            if sensor.auto_bypass:
                bypassable.append(BypassableSensor(
                    id=sensor.id,
                    name=sensor.name,
                    entity_id=sensor.entity_id,
                    auto_bypass=True,
                ))
                continue

            if sensor.arm_on_close:
                # arm_on_close sensors block until closed
                blocking.append(BlockingSensor(
                    id=sensor.id,
                    name=sensor.name,
                    entity_id=sensor.entity_id,
                    current_state="open",
                    reason="open",
                ))
                continue

            # Default: blocking
            blocking.append(BlockingSensor(
                id=sensor.id,
                name=sensor.name,
                entity_id=sensor.entity_id,
                current_state="open",
                reason="open",
            ))

        modes[mode] = ModeReadiness(
            ready=len(blocking) == 0,
            blocking_sensors=blocking,
            bypassable_sensors=bypassable,
        )

    return ReadyToArmResult(
        modes=modes,
        global_issues=global_issues,
    )
```

### Phase 2B: Ready-to-Arm API

**File:** `backend/alarm/views/ready_to_arm.py`

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from alarm.use_cases.ready_to_arm import get_ready_to_arm_status


class ReadyToArmView(APIView):
    """
    GET /api/alarm/ready-to-arm/

    Returns readiness status for each arm mode.
    """

    def get(self, request):
        result = get_ready_to_arm_status()

        return Response({
            "modes": {
                mode: {
                    "ready": readiness.ready,
                    "blocking_sensors": [
                        {
                            "id": s.id,
                            "name": s.name,
                            "entity_id": s.entity_id,
                            "current_state": s.current_state,
                            "reason": s.reason,
                        }
                        for s in readiness.blocking_sensors
                    ],
                    "bypassable_sensors": [
                        {
                            "id": s.id,
                            "name": s.name,
                            "entity_id": s.entity_id,
                            "auto_bypass": s.auto_bypass,
                        }
                        for s in readiness.bypassable_sensors
                    ],
                }
                for mode, readiness in result.modes.items()
            },
            "global_issues": result.global_issues,
        })
```

**File:** `backend/alarm/urls.py` (add route)

```python
from alarm.views.ready_to_arm import ReadyToArmView

urlpatterns = [
    # ... existing routes ...
    path("ready-to-arm/", ReadyToArmView.as_view(), name="ready-to-arm"),
]
```

### Phase 2C: WebSocket Updates

**File:** `backend/alarm/consumers.py` (add to existing consumer)

```python
async def broadcast_ready_to_arm(self):
    """Push ready-to-arm status when sensor states change."""
    from alarm.use_cases.ready_to_arm import get_ready_to_arm_status

    result = await database_sync_to_async(get_ready_to_arm_status)()

    await self.channel_layer.group_send(
        self.room_group_name,
        {
            "type": "ready_to_arm_changed",
            "payload": {
                "modes": {
                    mode: {
                        "ready": r.ready,
                        "blocking_sensors": [
                            {"id": s.id, "name": s.name, "entity_id": s.entity_id}
                            for s in r.blocking_sensors
                        ],
                    }
                    for mode, r in result.modes.items()
                },
            },
        }
    )
```

### Phase 2D: Frontend Types

**File:** `frontend/src/types/alarm.ts`

```typescript
// Enhanced Sensor type
export interface Sensor {
  id: number
  name: string
  entityId: string | null
  isActive: boolean

  // NEW: Classification
  sensorType: 'door' | 'window' | 'motion' | 'tamper' | 'environmental' | 'other'

  // NEW: Behavior flags
  alwaysOn: boolean
  useExitDelay: boolean
  useEntryDelay: boolean
  entryDelayOverride: number | null
  allowOpen: boolean
  autoBypass: boolean
  armOnClose: boolean
  triggerUnavailable: boolean
  enabledModes: string[]

  // Computed
  currentState: 'open' | 'closed' | 'unknown'
  lastTriggered: string | null
  usedInRules?: boolean

  // DEPRECATED
  isEntryPoint: boolean
}

// Ready-to-arm types
export interface BlockingSensor {
  id: number
  name: string
  entityId: string
  currentState: 'open' | 'unavailable'
  reason: 'open' | 'unavailable'
}

export interface BypassableSensor {
  id: number
  name: string
  entityId: string
  autoBypass: boolean
}

export interface ModeReadiness {
  ready: boolean
  blockingSensors: BlockingSensor[]
  bypassableSensors: BypassableSensor[]
}

export interface ReadyToArmResponse {
  modes: Record<string, ModeReadiness>
  globalIssues: string[]
}
```

### Phase 2E: Frontend Service

**File:** `frontend/src/services/readyToArm.ts`

```typescript
import { apiClient } from './api'
import type { ReadyToArmResponse } from '../types/alarm'

export const readyToArmService = {
  async getStatus(): Promise<ReadyToArmResponse> {
    return apiClient.get('/api/alarm/ready-to-arm/')
  },
}
```

### Phase 2F: Frontend Hook

**File:** `frontend/src/hooks/useReadyToArm.ts`

```typescript
import { useState, useEffect, useCallback } from 'react'
import { readyToArmService } from '../services/readyToArm'
import { useWebSocket } from './useWebSocket'
import type { ReadyToArmResponse } from '../types/alarm'

export function useReadyToArm() {
  const [status, setStatus] = useState<ReadyToArmResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const data = await readyToArmService.getStatus()
      setStatus(data)
      setError(null)
    } catch (err) {
      setError('Failed to fetch ready-to-arm status')
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial fetch
  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

  // WebSocket updates
  useWebSocket({
    onMessage: (message) => {
      if (message.type === 'ready_to_arm_changed') {
        setStatus(message.payload)
      }
    },
  })

  return { status, loading, error, refetch: fetchStatus }
}
```

---

## Frontend UI Changes

### Sensor Edit Form

Add new fields to sensor edit form:

```tsx
// Sensor type dropdown
<Select
  label="Sensor Type"
  value={sensor.sensorType}
  options={[
    { value: 'door', label: 'Door' },
    { value: 'window', label: 'Window' },
    { value: 'motion', label: 'Motion' },
    { value: 'tamper', label: 'Tamper' },
    { value: 'environmental', label: 'Environmental (Smoke/CO)' },
    { value: 'other', label: 'Other' },
  ]}
/>

// Behavior toggles
<Toggle label="Always On" sublabel="Trigger even when disarmed" />
<Toggle label="Use Exit Delay" sublabel="Ignore during arming countdown" />
<Toggle label="Use Entry Delay" sublabel="Wait before triggering alarm" />
<NumberInput label="Entry Delay Override" placeholder="Use system default" />
<Toggle label="Allow Open When Arming" />
<Toggle label="Auto-Bypass If Open" />
<Toggle label="Arm On Close" sublabel="Wait for sensor to close" />
<Toggle label="Trigger If Unavailable" />

// Mode selection
<MultiSelect
  label="Active In Modes"
  placeholder="All modes"
  options={['armed_away', 'armed_home', 'armed_night', 'armed_vacation']}
/>
```

### Arm Panel Enhancement

Show blocking sensors when trying to arm:

```tsx
function ArmButton({ mode }: { mode: string }) {
  const { status } = useReadyToArm()
  const modeStatus = status?.modes[mode]

  if (!modeStatus?.ready) {
    return (
      <div>
        <Button disabled>
          Arm {mode}
        </Button>
        <div className="text-red-500 text-sm mt-1">
          {modeStatus?.blockingSensors.map(s => (
            <div key={s.id}>• {s.name} is {s.reason}</div>
          ))}
        </div>
      </div>
    )
  }

  return <Button onClick={() => arm(mode)}>Arm {mode}</Button>
}
```

---

## Testing Strategy

### Unit Tests

```python
# test_sensor_behaviors.py

def test_always_on_sensor_triggers_when_disarmed():
    """Always-on sensors (smoke) trigger even when disarmed."""
    sensor = Sensor.objects.create(
        name="Smoke Detector",
        entity_id="binary_sensor.smoke",
        always_on=True,
    )
    # Ensure alarm is disarmed
    snapshot = get_current_snapshot()
    assert snapshot.current_state == AlarmState.DISARMED

    # Trigger sensor
    result = sensor_triggered(sensor=sensor)

    # Should be triggered even though disarmed
    assert result.current_state == AlarmState.TRIGGERED


def test_sensor_without_exit_delay_aborts_arming():
    """Sensors without exit delay abort arming when tripped."""
    sensor = Sensor.objects.create(
        name="Motion Sensor",
        entity_id="binary_sensor.motion",
        use_exit_delay=False,
    )
    # Start arming
    arm(target_state=AlarmState.ARMED_AWAY)
    snapshot = get_current_snapshot()
    assert snapshot.current_state == AlarmState.ARMING

    # Trigger sensor
    result = sensor_triggered(sensor=sensor)

    # Should abort arming
    assert result.current_state == AlarmState.DISARMED


def test_per_sensor_entry_delay():
    """Sensors can override system entry delay."""
    sensor = Sensor.objects.create(
        name="Back Door",
        entity_id="binary_sensor.back_door",
        use_entry_delay=True,
        entry_delay_override=15,  # 15 seconds instead of system default
    )
    # Arm the system
    arm(target_state=AlarmState.ARMED_AWAY)

    # Trigger sensor
    result = sensor_triggered(sensor=sensor)

    # Should be pending with 15 second delay
    assert result.current_state == AlarmState.PENDING
    # exit_at should be ~15 seconds from now


def test_ready_to_arm_with_open_sensor():
    """Ready-to-arm shows blocking sensors."""
    sensor = Sensor.objects.create(
        name="Front Door",
        entity_id="binary_sensor.front_door",
    )
    # Mock sensor as open
    mock_entity_state("binary_sensor.front_door", "on")

    result = get_ready_to_arm_status()

    assert result.modes["armed_away"].ready is False
    assert len(result.modes["armed_away"].blocking_sensors) == 1
    assert result.modes["armed_away"].blocking_sensors[0].name == "Front Door"


def test_auto_bypass_sensor_not_blocking():
    """Auto-bypass sensors don't block arming."""
    sensor = Sensor.objects.create(
        name="Garage Door",
        entity_id="binary_sensor.garage",
        auto_bypass=True,
    )
    mock_entity_state("binary_sensor.garage", "on")

    result = get_ready_to_arm_status()

    assert result.modes["armed_away"].ready is True
    assert len(result.modes["armed_away"].bypassable_sensors) == 1
```

### Integration Tests

```python
# test_enhanced_sensors_integration.py

def test_full_arming_flow_with_open_sensor():
    """Test arming with open sensor that gets bypassed."""
    # Create sensor with auto_bypass
    sensor = create_sensor(auto_bypass=True)

    # Set sensor to open state
    set_entity_state(sensor.entity_id, "on")

    # Check ready-to-arm
    response = client.get("/api/alarm/ready-to-arm/")
    assert response.data["modes"]["armed_away"]["ready"] is True

    # Arm should succeed with sensor bypassed
    response = client.post("/api/alarm/arm/", {"mode": "armed_away"})
    assert response.status_code == 200

    # Verify sensor is recorded as bypassed
    snapshot = AlarmStateSnapshot.objects.current()
    assert sensor.id in snapshot.bypassed_sensor_ids
```

---

## Migration Path

### Backward Compatibility

1. Keep `is_entry_point` field (deprecated but functional)
2. New `use_entry_delay` defaults to matching `is_entry_point` value
3. API returns both old and new fields
4. Frontend can use either until fully migrated

### Rollout Steps

1. Deploy backend with new fields (migration)
2. Deploy frontend with new sensor edit form
3. Users configure sensors with new behavior flags
4. Remove `is_entry_point` in future release (v2.0)

---

## Open Questions

1. **Bypassed sensors tracking** - Should bypassed sensors be stored in the snapshot? (Alarmo does this)
2. **Sensor groups** - Defer to Phase 4 or include basic support?
3. **Force arm** - Allow arming with blocking sensors via override code?
4. **Notifications** - Add notification on "ready to arm" status change?

---

## Acceptance Criteria

### Phase 1: Enhanced Sensors

- [ ] New sensor fields in database
- [ ] Migration preserves existing behavior via smart defaults
- [ ] Sensor edit form shows all new fields
- [ ] Always-on sensors trigger when disarmed
- [ ] Sensors respect use_exit_delay during arming
- [ ] Per-sensor entry delay works
- [ ] Mode filtering works
- [ ] All existing tests pass
- [ ] New unit tests for each behavior

### Phase 2: Ready-to-Arm

- [ ] GET /api/alarm/ready-to-arm/ endpoint works
- [ ] Response includes all modes with blocking/bypassable sensors
- [ ] WebSocket pushes updates on sensor state changes
- [ ] Frontend shows blocking sensors on arm panel
- [ ] Frontend disables arm buttons when not ready
- [ ] Loading and error states handled

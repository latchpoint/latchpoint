from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from integrations_frigate.models import FrigateDetection
from integrations_home_assistant import api as home_assistant

from accounts.models import Role, User, UserCode, UserCodeAllowedState, UserRoleAssignment
from alarm.crypto import SettingsEncryption
from alarm.models import (
    AlarmEvent,
    AlarmEventType,
    AlarmSettingsProfile,
    AlarmStateSnapshot,
    AlarmSystem,
    Entity,
    EntityTag,
    Rule,
    RuleActionLog,
    RuleEntityRef,
    RuleRuntimeState,
    Sensor,
)
from alarm.state_machine.transitions import get_current_snapshot
from control_panels.models import (
    ControlPanelDevice,
    ControlPanelIntegrationType,
    ControlPanelKind,
)
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from notifications.models import NotificationProvider


@dataclass(frozen=True)
class SeedEntitiesConfig:
    entry_entity_id: str
    motion_entity_id: str
    extra_entity_ids: list[str]


# Demo entity_ids used when --demo runs without a real Home Assistant available.
_DEMO_ENTITY_IDS: dict[str, dict[str, str]] = {
    "binary_sensor.front_door_demo": {
        "domain": "binary_sensor",
        "name": "Front Door",
        "device_class": "door",
    },
    "binary_sensor.back_door_demo": {
        "domain": "binary_sensor",
        "name": "Back Door",
        "device_class": "door",
    },
    "binary_sensor.living_room_motion_demo": {
        "domain": "binary_sensor",
        "name": "Living Room Motion",
        "device_class": "motion",
    },
    "binary_sensor.garage_motion_demo": {
        "domain": "binary_sensor",
        "name": "Garage Motion",
        "device_class": "motion",
    },
    "binary_sensor.upstairs_window_demo": {
        "domain": "binary_sensor",
        "name": "Upstairs Window",
        "device_class": "window",
    },
    "binary_sensor.kitchen_smoke_demo": {
        "domain": "binary_sensor",
        "name": "Kitchen Smoke Alarm",
        "device_class": "smoke",
    },
    "lock.front_door_lock_demo": {
        "domain": "lock",
        "name": "Front Door Lock",
        "device_class": "",
    },
    "lock.garage_lock_demo": {
        "domain": "lock",
        "name": "Garage Lock",
        "device_class": "",
    },
    "light.porch_light_demo": {
        "domain": "light",
        "name": "Porch Light",
        "device_class": "",
    },
    "switch.driveway_camera_demo": {
        "domain": "switch",
        "name": "Driveway Camera Power",
        "device_class": "",
    },
}


def _load_entities_config(path: Path, *, allow_missing: bool = False) -> SeedEntitiesConfig:
    """Load the seed entities config JSON file and validate its shape.

    With ``allow_missing=True``, a missing or empty file returns an empty
    config rather than raising. This is used by ``--demo`` mode where the file
    is optional and demo entity_ids are fabricated instead.
    """
    try:
        text = path.read_text(encoding="utf-8") or "{}"
    except FileNotFoundError as exc:
        if allow_missing:
            return SeedEntitiesConfig(entry_entity_id="", motion_entity_id="", extra_entity_ids=[])
        raise CommandError(f"Entities config file not found: {path}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CommandError(f"Invalid JSON in entities config file: {path}") from exc

    if not isinstance(raw, dict):
        raise CommandError("Entities config must be a JSON object.")

    entry_entity_id = (raw.get("entry_entity_id") or "").strip()
    motion_entity_id = (raw.get("motion_entity_id") or "").strip()
    extra_raw = raw.get("extra_entity_ids") or []
    extra_entity_ids: list[str] = []
    if isinstance(extra_raw, list):
        for item in extra_raw:
            if isinstance(item, str) and item.strip():
                extra_entity_ids.append(item.strip())
    return SeedEntitiesConfig(
        entry_entity_id=entry_entity_id,
        motion_entity_id=motion_entity_id,
        extra_entity_ids=sorted(set(extra_entity_ids)),
    )


def _ensure_active_settings_profile() -> AlarmSettingsProfile:
    """Ensure an active settings profile exists for the demo seed data."""
    profile = AlarmSettingsProfile.objects.filter(is_active=True).first()
    if profile:
        return profile
    existing = AlarmSettingsProfile.objects.first()
    if existing:
        existing.is_active = True
        existing.save(update_fields=["is_active"])
        return existing
    return AlarmSettingsProfile.objects.create(name="Default", is_active=True)


def _ensure_secondary_profile() -> AlarmSettingsProfile:
    """Create an inactive 'Vacation' profile so the profile-switcher UI has variety."""
    profile, _ = AlarmSettingsProfile.objects.get_or_create(
        name="Vacation",
        defaults={"is_active": False},
    )
    return profile


def _get_role(slug: str, *, name: str, description: str) -> Role:
    """Fetch or create a role row by slug."""
    role, _ = Role.objects.get_or_create(
        slug=slug,
        defaults={"name": name, "description": description},
    )
    return role


def _assign_role(*, user: User, role_slug: str) -> None:
    """Assign a role to a user, creating the role if needed."""
    role_defaults = {
        "admin": ("Admin", "Full administrative access"),
        "resident": ("Resident", "Resident access"),
        "guest": ("Guest", "Guest access"),
        "service": ("Service", "Service access"),
    }
    name, description = role_defaults.get(role_slug, (role_slug.title(), ""))
    role = _get_role(role_slug, name=name, description=description)
    UserRoleAssignment.objects.get_or_create(
        user=user,
        role=role,
        defaults={"assigned_by": user if role_slug == "admin" else None},
    )


def _create_code(
    *,
    user: User,
    label: str,
    raw_code: str,
    code_type: str,
    allowed_states: list[str] | None = None,
    start_at=None,
    end_at=None,
    days_of_week: int | None = None,
    window_start=None,
    window_end=None,
    max_uses: int | None = None,
) -> UserCode:
    """Create a `UserCode` and its allowed states."""
    code = UserCode.objects.create(
        user=user,
        code_hash=make_password(raw_code),
        label=label,
        code_type=code_type,
        pin_length=len(raw_code),
        is_active=True,
        max_uses=max_uses,
        start_at=start_at,
        end_at=end_at,
        days_of_week=days_of_week,
        window_start=window_start,
        window_end=window_end,
    )
    for state in allowed_states or []:
        UserCodeAllowedState.objects.create(code=code, state=state)
    return code


def _sync_entities_from_home_assistant(*, now) -> tuple[int, int, set[str]]:
    """Sync entities from Home Assistant into the local entity registry (best-effort)."""
    imported = 0
    updated = 0
    seen: set[str] = set()
    for item in home_assistant.list_entities():
        if not isinstance(item, dict):
            continue
        entity_id = item.get("entity_id")
        domain = item.get("domain")
        name = item.get("name")
        if not isinstance(entity_id, str) or "." not in entity_id:
            continue
        if not isinstance(domain, str) or not domain:
            domain = entity_id.split(".", 1)[0]
        if not isinstance(name, str) or not name:
            name = entity_id

        device_class = item.get("device_class") if isinstance(item.get("device_class"), str) else None
        last_state = item.get("state") if isinstance(item.get("state"), str) else None
        last_changed_raw = item.get("last_changed") if isinstance(item.get("last_changed"), str) else None
        last_changed = parse_datetime(last_changed_raw) if last_changed_raw else None

        defaults = {
            "domain": domain,
            "name": name,
            "device_class": device_class,
            "last_state": last_state,
            "last_changed": last_changed,
            "last_seen": now,
            "attributes": {"unit_of_measurement": item.get("unit_of_measurement")},
            "source": "home_assistant",
        }
        obj, created = Entity.objects.update_or_create(entity_id=entity_id, defaults=defaults)
        imported += 1 if created else 0
        updated += 0 if created else 1
        seen.add(obj.entity_id)
    return imported, updated, seen


def _seed_demo_entities(*, now) -> set[str]:
    """Create fabricated `Entity` rows for offline demo mode."""
    seen: set[str] = set()
    for entity_id, meta in _DEMO_ENTITY_IDS.items():
        Entity.objects.update_or_create(
            entity_id=entity_id,
            defaults={
                "domain": meta["domain"],
                "name": meta["name"],
                "device_class": meta["device_class"] or None,
                "last_state": "off" if meta["domain"] == "binary_sensor" else "unknown",
                "last_changed": now,
                "last_seen": now,
                "attributes": {},
                "source": "demo_seed",
            },
        )
        seen.add(entity_id)
    return seen


def _seed_entity_tags() -> dict[str, EntityTag]:
    """Create a small set of entity tags for the entity tagging UI."""
    tags: dict[str, EntityTag] = {}
    for name, color in (
        ("Doors", "#3b82f6"),
        ("Motion", "#a855f7"),
        ("Critical", "#ef4444"),
        ("Outdoor", "#22c55e"),
    ):
        tag, _ = EntityTag.objects.get_or_create(name=name, defaults={"color": color})
        tags[name] = tag
    return tags


def _apply_entity_tags(tags: dict[str, EntityTag]) -> None:
    """Tag a few demo entities so the entity tagging filter UI has data to show."""
    mappings: list[tuple[str, list[str]]] = [
        ("binary_sensor.front_door_demo", ["Doors", "Critical"]),
        ("binary_sensor.back_door_demo", ["Doors"]),
        ("binary_sensor.living_room_motion_demo", ["Motion"]),
        ("binary_sensor.garage_motion_demo", ["Motion", "Outdoor"]),
        ("binary_sensor.upstairs_window_demo", ["Doors"]),
        ("binary_sensor.kitchen_smoke_demo", ["Critical"]),
    ]
    for entity_id, tag_names in mappings:
        entity = Entity.objects.filter(entity_id=entity_id).first()
        if not entity:
            continue
        entity.tags.set([tags[name] for name in tag_names if name in tags])


def _seed_demo_sensors(entity_ids: list[str]) -> None:
    """Create `Sensor` rows for the fabricated demo entities."""
    sensor_rows: list[tuple[str, str, bool]] = [
        ("[demo] Front Door", "binary_sensor.front_door_demo", True),
        ("[demo] Back Door", "binary_sensor.back_door_demo", True),
        ("[demo] Living Room Motion", "binary_sensor.living_room_motion_demo", False),
        ("[demo] Garage Motion", "binary_sensor.garage_motion_demo", False),
        ("[demo] Upstairs Window", "binary_sensor.upstairs_window_demo", False),
        ("[demo] Kitchen Smoke", "binary_sensor.kitchen_smoke_demo", False),
    ]
    available = set(entity_ids)
    for name, entity_id, is_entry in sensor_rows:
        if entity_id not in available:
            continue
        Sensor.objects.update_or_create(
            entity_id=entity_id,
            defaults={"name": name, "is_active": True, "is_entry_point": is_entry},
        )


def _seed_demo_rules(*, admin_user: User) -> list[Rule]:
    """Create a varied set of rules so the rules list and builder pages have data."""
    front_door = "binary_sensor.front_door_demo"
    back_door = "binary_sensor.back_door_demo"
    living_motion = "binary_sensor.living_room_motion_demo"
    garage_motion = "binary_sensor.garage_motion_demo"
    smoke = "binary_sensor.kitchen_smoke_demo"
    porch_light = "light.porch_light_demo"

    rule_specs: list[tuple[str, str, int, dict[str, Any]]] = [
        (
            "[demo] Trigger on front door open while armed away",
            "trigger",
            100,
            {
                "when": {
                    "op": "and",
                    "children": [
                        {"op": "entity_state", "entity_id": front_door, "equals": "on"},
                        {"op": "alarm_state", "in": ["armed_away", "armed_night"]},
                    ],
                },
                "then": [{"type": "alarm_trigger"}],
            },
        ),
        (
            "[demo] Trigger on smoke alarm (any state)",
            "trigger",
            120,
            {
                "when": {"op": "entity_state", "entity_id": smoke, "equals": "on"},
                "then": [{"type": "alarm_trigger"}],
            },
        ),
        (
            "[demo] Trigger on persistent garage motion (10s) when armed away",
            "trigger",
            80,
            {
                "when": {
                    "op": "and",
                    "children": [
                        {"op": "alarm_state", "in": ["armed_away"]},
                        {
                            "op": "for",
                            "seconds": 10,
                            "child": {"op": "entity_state", "entity_id": garage_motion, "equals": "on"},
                        },
                    ],
                },
                "then": [{"type": "alarm_trigger"}],
            },
        ),
        (
            "[demo] Suppress living-room motion at night (pets)",
            "suppress",
            60,
            {
                "when": {
                    "op": "and",
                    "children": [
                        {"op": "entity_state", "entity_id": living_motion, "equals": "on"},
                        {"op": "alarm_state", "in": ["armed_home", "armed_night"]},
                    ],
                },
                "then": [],
            },
        ),
        (
            "[demo] Auto-arm at 11pm if disarmed",
            "arm",
            40,
            {
                "when": {
                    "op": "time_of_day",
                    "after": "23:00",
                    "before": "23:05",
                },
                "then": [{"type": "alarm_arm", "state": "armed_night"}],
            },
        ),
        (
            "[demo] Disarm when back door opens with valid code",
            "disarm",
            30,
            {
                "when": {"op": "entity_state", "entity_id": back_door, "equals": "on"},
                "then": [{"type": "alarm_disarm"}],
            },
        ),
        (
            "[demo] Escalate: turn on porch light when alarm triggers",
            "escalate",
            20,
            {
                "when": {"op": "alarm_state", "in": ["triggered"]},
                "then": [
                    {
                        "type": "ha_call_service",
                        "service": "light.turn_on",
                        "target": {"entity_id": porch_light},
                        "data": {"brightness_pct": 100},
                    }
                ],
            },
        ),
        (
            "[demo] Notify all providers on trigger",
            "escalate",
            10,
            {
                "when": {"op": "alarm_state", "in": ["triggered"]},
                "then": [
                    {
                        "type": "send_notification",
                        "title": "Alarm triggered",
                        "message": "Your alarm system was triggered.",
                    }
                ],
            },
        ),
    ]

    created: list[Rule] = []
    for name, kind, priority, definition in rule_specs:
        rule = Rule.objects.create(
            name=name,
            kind=kind,
            enabled=True,
            priority=priority,
            schema_version=1,
            definition=definition,
            cooldown_seconds=15,
            created_by=admin_user,
        )
        created.append(rule)
        for entity_id in {front_door, back_door, living_motion, garage_motion, smoke, porch_light}:
            entity = Entity.objects.filter(entity_id=entity_id).first()
            if entity and json.dumps(definition).find(entity_id) >= 0:
                RuleEntityRef.objects.get_or_create(rule=rule, entity=entity)
    return created


def _enable_demo_integrations(*, profile: AlarmSettingsProfile) -> None:
    """Mark every integration as enabled with realistic-looking config in the demo profile.

    Status endpoints (HA, MQTT, Z-Wave JS, Frigate, Z2M) probe live brokers, so the
    screenshot harness mocks them out. The settings *entries* drive the
    enabled/configured pills on the settings pages; we set them here so the UI
    shows configured values and "Enabled" toggles in the on position.
    """
    from alarm.models import AlarmSettingsEntry
    from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY

    overrides: dict[str, dict[str, Any]] = {
        "home_assistant": {
            "enabled": True,
            "base_url": "http://homeassistant.demo.local:8123",
            "token": "demo-long-lived-access-token-value",
        },
        "mqtt": {
            "enabled": True,
            "host": "mosquitto.demo.local",
            "port": 1883,
            "username": "latchpoint",
            "password": "demo-broker-password",
        },
        "zwavejs": {
            "enabled": True,
            "ws_url": "ws://zwavejs.demo.local:3000",
            "api_token": "demo-zwavejs-api-token",
        },
        "frigate": {
            "enabled": True,
            "events_topic": "frigate/events",
            "known_cameras": ["driveway", "front_door", "back_yard"],
            "known_zones_by_camera": {
                "driveway": ["walkway", "driveway"],
                "front_door": ["porch"],
                "back_yard": ["lawn", "patio"],
            },
        },
        "zigbee2mqtt": {
            "enabled": True,
            "base_topic": "zigbee2mqtt",
        },
        "ha_mqtt_alarm_entity": {
            "enabled": True,
            "entity_name": "Latchpoint",
            "ha_entity_id": "alarm_control_panel.latchpoint_alarm",
        },
    }

    for key, value in overrides.items():
        definition = ALARM_PROFILE_SETTINGS_BY_KEY.get(key)
        if definition is None:
            continue
        entry, _ = AlarmSettingsEntry.objects.get_or_create(
            profile=profile,
            key=key,
            defaults={"value": dict(definition.default), "value_type": definition.value_type},
        )
        entry.set_value_with_encryption(value, partial=True)


def _seed_notification_providers(*, profile: AlarmSettingsProfile) -> None:
    """Create one provider per common handler with realistic-looking encrypted secrets."""
    providers: list[tuple[str, str, dict[str, Any]]] = [
        (
            "[demo] Family Pushbullet",
            "pushbullet",
            {"access_token": "o.demoTOKENvalueforPushbullet1234567890"},
        ),
        (
            "[demo] House Discord",
            "discord",
            {
                "webhook_url": "https://discord.com/api/webhooks/123456789012345678/demoWebhookSecretValue",
                "username": "Latchpoint",
            },
        ),
        (
            "[demo] Home Slack",
            "slack",
            {
                "bot_token": "xoxb-demo-slack-bot-token-value",
                "channel": "#alarm-alerts",
            },
        ),
        (
            "[demo] Custom webhook",
            "webhook",
            {
                "url": "https://example.invalid/hooks/latchpoint",
                "method": "POST",
                "auth_type": "bearer",
                "auth_value": "demo-bearer-token-value",
            },
        ),
        (
            "[demo] Home Assistant push",
            "home_assistant",
            {"service": "notify.mobile_app_pixel"},
        ),
    ]
    for name, provider_type, config in providers:
        provider, created = NotificationProvider.objects.update_or_create(
            profile=profile,
            name=name,
            defaults={
                "provider_type": provider_type,
                "is_enabled": True,
            },
        )
        # set_config_with_encryption handles the encryption for fields the handler declares.
        provider.set_config_with_encryption(config, partial=False, save=True)


def _seed_door_codes(*, residents: list[User], now) -> None:
    """Create varied door codes assigned to two demo locks."""
    encryption = SettingsEncryption.get()
    front_lock = "lock.front_door_lock_demo"
    garage_lock = "lock.garage_lock_demo"

    door_specs: list[dict[str, Any]] = [
        {
            "user": residents[0],
            "label": "[demo] Resident permanent",
            "raw_pin": "445566",
            "code_type": DoorCode.CodeType.PERMANENT,
            "locks": [front_lock, garage_lock],
            "max_uses": None,
            "start_at": None,
            "end_at": None,
            "days_of_week": None,
            "window_start": None,
            "window_end": None,
        },
        {
            "user": residents[1],
            "label": "[demo] Cleaner Tue/Thu mornings",
            "raw_pin": "778899",
            "code_type": DoorCode.CodeType.SERVICE,
            "locks": [front_lock],
            "max_uses": None,
            "start_at": None,
            "end_at": None,
            # Bitmask: Tue (1<<1=2) + Thu (1<<3=8) = 10
            "days_of_week": 10,
            "window_start": time(8, 0),
            "window_end": time(12, 0),
        },
        {
            "user": residents[2],
            "label": "[demo] Guest weekend stay",
            "raw_pin": "112233",
            "code_type": DoorCode.CodeType.TEMPORARY,
            "locks": [front_lock],
            "max_uses": None,
            "start_at": now - timedelta(days=2),
            "end_at": now + timedelta(days=5),
            "days_of_week": None,
            "window_start": None,
            "window_end": None,
        },
        {
            "user": residents[2],
            "label": "[demo] Delivery one-time",
            "raw_pin": "989898",
            "code_type": DoorCode.CodeType.ONE_TIME,
            "locks": [front_lock],
            "max_uses": 1,
            "start_at": now,
            "end_at": now + timedelta(hours=4),
            "days_of_week": None,
            "window_start": None,
            "window_end": None,
        },
        {
            "user": residents[0],
            "label": "[demo] Garage-only spare",
            "raw_pin": "246810",
            "code_type": DoorCode.CodeType.PERMANENT,
            "locks": [garage_lock],
            "max_uses": None,
            "start_at": None,
            "end_at": None,
            "days_of_week": None,
            "window_start": None,
            "window_end": None,
        },
    ]

    for slot, spec in enumerate(door_specs, start=1):
        code = DoorCode.objects.create(
            user=spec["user"],
            source=DoorCode.Source.MANUAL,
            encrypted_pin=encryption.encrypt(spec["raw_pin"]),
            label=spec["label"],
            code_type=spec["code_type"],
            pin_length=len(spec["raw_pin"]),
            is_active=True,
            max_uses=spec["max_uses"],
            uses_count=0,
            start_at=spec["start_at"],
            end_at=spec["end_at"],
            days_of_week=spec["days_of_week"],
            window_start=spec["window_start"],
            window_end=spec["window_end"],
        )
        for idx, lock_entity_id in enumerate(spec["locks"]):
            DoorCodeLockAssignment.objects.create(
                door_code=code,
                lock_entity_id=lock_entity_id,
                slot_index=slot + idx,
            )

    _seed_door_code_events(now=now)


def _seed_door_code_events(*, now) -> None:
    """Create a handful of door-code audit events so the door codes page has history."""
    codes = list(DoorCode.objects.filter(label__startswith="[demo]").order_by("id"))
    if not codes:
        return
    samples: list[tuple[int, str, str, int]] = [
        (0, DoorCodeEvent.EventType.CODE_USED, "lock.front_door_lock_demo", 6),
        (0, DoorCodeEvent.EventType.CODE_USED, "lock.garage_lock_demo", 30),
        (1, DoorCodeEvent.EventType.CODE_USED, "lock.front_door_lock_demo", 26),
        (2, DoorCodeEvent.EventType.CODE_USED, "lock.front_door_lock_demo", 12),
        (3, DoorCodeEvent.EventType.CODE_FAILED, "lock.front_door_lock_demo", 3),
        (3, DoorCodeEvent.EventType.CODE_USED, "lock.front_door_lock_demo", 2),
        (4, DoorCodeEvent.EventType.CODE_SYNCED, "lock.garage_lock_demo", 50),
    ]
    for code_idx, event_type, lock_entity_id, hours_ago in samples:
        if code_idx >= len(codes):
            continue
        code = codes[code_idx]
        DoorCodeEvent.objects.create(
            door_code=code,
            user=code.user,
            lock_entity_id=lock_entity_id,
            event_type=event_type,
            metadata={"slot_index": 1, "demo": True},
            created_at=now - timedelta(hours=hours_ago),
        )


def _seed_control_panel() -> None:
    """Create a Ring Keypad v2 control panel device with a default action map."""
    ControlPanelDevice.objects.update_or_create(
        external_key="zwavejs:demo-home:42",
        defaults={
            "name": "[demo] Front Hallway Keypad",
            "integration_type": ControlPanelIntegrationType.ZWAVEJS,
            "kind": ControlPanelKind.RING_KEYPAD_V2,
            "enabled": True,
            "external_id": {"home_id": "demo-home", "node_id": 42},
            "beep_volume": 60,
            "action_map": {
                "disarm": "disarmed",
                "arm_home": "armed_home",
                "arm_away": "armed_away",
                "cancel": "cancel_arming",
            },
        },
    )


def _seed_alarm_event_history(*, now, admin_user: User) -> None:
    """Create alarm/event rows spanning the past week so the events page has data."""
    sensors = {s.entity_id: s for s in Sensor.objects.filter(name__startswith="[demo]")}
    front_door_sensor = sensors.get("binary_sensor.front_door_demo")
    motion_sensor = sensors.get("binary_sensor.living_room_motion_demo")
    smoke_sensor = sensors.get("binary_sensor.kitchen_smoke_demo")

    events: list[dict[str, Any]] = [
        # 6 days ago: morning routine
        {"type": AlarmEventType.DISARMED, "from": "armed_night", "to": "disarmed", "hours": 144, "user": admin_user},
        {
            "type": AlarmEventType.STATE_CHANGED,
            "from": "disarmed",
            "to": "armed_away",
            "hours": 142,
            "user": admin_user,
        },
        {"type": AlarmEventType.ARMED, "from": "armed_away", "to": "armed_away", "hours": 142, "user": admin_user},
        {"type": AlarmEventType.SENSOR_TRIGGERED, "from": None, "to": None, "hours": 140, "sensor": front_door_sensor},
        {"type": AlarmEventType.DISARMED, "from": "armed_away", "to": "disarmed", "hours": 134, "user": admin_user},
        # 4 days ago: false trigger
        {"type": AlarmEventType.STATE_CHANGED, "from": "disarmed", "to": "armed_home", "hours": 96, "user": admin_user},
        {"type": AlarmEventType.SENSOR_TRIGGERED, "from": None, "to": None, "hours": 95, "sensor": motion_sensor},
        {"type": AlarmEventType.TRIGGERED, "from": "armed_home", "to": "triggered", "hours": 95},
        {"type": AlarmEventType.DISARMED, "from": "triggered", "to": "disarmed", "hours": 94, "user": admin_user},
        {"type": AlarmEventType.FAILED_CODE, "from": None, "to": None, "hours": 94, "user": admin_user},
        # 2 days ago: smoke check
        {"type": AlarmEventType.SENSOR_TRIGGERED, "from": None, "to": None, "hours": 50, "sensor": smoke_sensor},
        {
            "type": AlarmEventType.INTEGRATION_OFFLINE,
            "from": None,
            "to": None,
            "hours": 49,
            "metadata": {"integration": "mqtt"},
        },
        {
            "type": AlarmEventType.INTEGRATION_RECOVERED,
            "from": None,
            "to": None,
            "hours": 48,
            "metadata": {"integration": "mqtt"},
        },
        # 1 day ago: typical evening
        {
            "type": AlarmEventType.STATE_CHANGED,
            "from": "disarmed",
            "to": "armed_night",
            "hours": 30,
            "user": admin_user,
        },
        {"type": AlarmEventType.ARMED, "from": "armed_night", "to": "armed_night", "hours": 30, "user": admin_user},
        {"type": AlarmEventType.CODE_USED, "from": None, "to": None, "hours": 29, "user": admin_user},
        # Today
        {"type": AlarmEventType.DISARMED, "from": "armed_night", "to": "disarmed", "hours": 18, "user": admin_user},
        {"type": AlarmEventType.STATE_CHANGED, "from": "disarmed", "to": "armed_away", "hours": 9, "user": admin_user},
        {"type": AlarmEventType.ARMED, "from": "armed_away", "to": "armed_away", "hours": 9, "user": admin_user},
        {"type": AlarmEventType.SENSOR_TRIGGERED, "from": None, "to": None, "hours": 4, "sensor": front_door_sensor},
        {"type": AlarmEventType.DISARMED, "from": "armed_away", "to": "disarmed", "hours": 3, "user": admin_user},
    ]
    for spec in events:
        AlarmEvent.objects.create(
            event_type=spec["type"],
            state_from=spec.get("from"),
            state_to=spec.get("to"),
            timestamp=now - timedelta(hours=spec["hours"]),
            user=spec.get("user"),
            sensor=spec.get("sensor"),
            metadata=spec.get("metadata") or {},
        )


def _seed_frigate_detections(*, now) -> None:
    """Create a few Frigate detection rows so the Frigate settings/events have data."""
    detections: list[dict[str, Any]] = [
        {
            "label": "person",
            "camera": "driveway",
            "zones": ["walkway"],
            "confidence_pct": 92.4,
            "hours": 2,
            "event_id": "demo-evt-001",
        },
        {
            "label": "person",
            "camera": "front_door",
            "zones": ["porch"],
            "confidence_pct": 88.7,
            "hours": 4,
            "event_id": "demo-evt-002",
        },
        {
            "label": "car",
            "camera": "driveway",
            "zones": ["driveway"],
            "confidence_pct": 95.1,
            "hours": 6,
            "event_id": "demo-evt-003",
        },
        {
            "label": "package",
            "camera": "front_door",
            "zones": ["porch"],
            "confidence_pct": 71.2,
            "hours": 18,
            "event_id": "demo-evt-004",
        },
        {
            "label": "person",
            "camera": "back_yard",
            "zones": ["lawn", "patio"],
            "confidence_pct": 85.0,
            "hours": 30,
            "event_id": "demo-evt-005",
        },
        {
            "label": "dog",
            "camera": "back_yard",
            "zones": ["lawn"],
            "confidence_pct": 78.6,
            "hours": 50,
            "event_id": "demo-evt-006",
        },
    ]
    for spec in detections:
        FrigateDetection.objects.update_or_create(
            provider="frigate",
            event_id=spec["event_id"],
            defaults={
                "label": spec["label"],
                "camera": spec["camera"],
                "zones": spec["zones"],
                "confidence_pct": spec["confidence_pct"],
                "observed_at": now - timedelta(hours=spec["hours"]),
                "source_topic": f"frigate/events/{spec['camera']}",
                "raw": {"demo": True},
            },
        )


def _delete_all_seed_data() -> None:
    """Destructively delete app data to reset the DB before seeding."""
    # Demo-only models first (FKs into accounts/alarm tables).
    DoorCodeEvent.objects.all().delete()
    DoorCodeLockAssignment.objects.all().delete()
    DoorCode.objects.all().delete()
    ControlPanelDevice.objects.all().delete()
    NotificationProvider.objects.all().delete()
    FrigateDetection.objects.all().delete()

    RuleEntityRef.objects.all().delete()
    RuleRuntimeState.objects.all().delete()
    RuleActionLog.objects.all().delete()
    Rule.objects.all().delete()
    Sensor.objects.all().delete()
    EntityTag.objects.all().delete()
    Entity.objects.all().delete()

    AlarmEvent.objects.all().delete()
    AlarmStateSnapshot.objects.all().delete()
    AlarmSettingsProfile.objects.all().delete()
    AlarmSystem.objects.all().delete()

    from rest_framework.authtoken.models import Token

    Token.objects.all().delete()
    UserCodeAllowedState.objects.all().delete()
    UserCode.objects.all().delete()
    UserRoleAssignment.objects.all().delete()
    User.objects.all().delete()


class Command(BaseCommand):
    help = (
        "Destructively seed the database with a demo home dataset. Use --demo for a "
        "fully populated showcase dataset (notification providers, door codes, control "
        "panel, rules, alarm events, Frigate detections) without needing a live "
        "Home Assistant connection."
    )

    def add_arguments(self, parser):
        """Register CLI arguments for the seed command."""
        parser.add_argument(
            "--entities-file",
            default="schema/seed_entities.json",
            help=(
                "Path to JSON file specifying which HA entities to use for sensors/rules. "
                "Relative paths resolve against the repo root (BASE_DIR.parent), not cwd."
            ),
        )
        parser.add_argument(
            "--no-ha-sync",
            action="store_true",
            help="Skip syncing entities from Home Assistant (still seeds users/codes/rules).",
        )
        parser.add_argument(
            "--demo",
            action="store_true",
            help=(
                "Populate a comprehensive showcase dataset for screenshots/dev. "
                "Implies --no-ha-sync, fabricates demo entities, and seeds notification "
                "providers, door codes, control panel, extra rules, alarm event history, "
                "and Frigate detections."
            ),
        )

    def handle(self, *args, **options):
        """Seed the database with a demo home dataset (destructive)."""
        demo_mode = options["demo"]
        skip_ha_sync = options["no_ha_sync"] or demo_mode

        # Resolve relative paths against the repo root (BASE_DIR.parent), not cwd.
        # BASE_DIR is /app/backend; BASE_DIR.parent is /app, so the default
        # 'schema/seed_entities.json' lands at /app/schema/seed_entities.json.
        entities_file = Path(options["entities_file"]).expanduser()
        if not entities_file.is_absolute():
            entities_file = Path(settings.BASE_DIR).parent / entities_file

        config = _load_entities_config(entities_file, allow_missing=demo_mode)

        if not demo_mode and (not config.entry_entity_id or not config.motion_entity_id):
            raise CommandError(
                f"Missing entity IDs in {entities_file}. Set both "
                f"`entry_entity_id` and `motion_entity_id` to real Home Assistant entity_ids, "
                f"or pass --demo to seed a synthetic demo dataset."
            )

        # Status fetch is cheap and informational; only enforce reachability if we'll sync.
        status_obj = home_assistant.get_status()
        if not skip_ha_sync:
            if not status_obj.configured:
                raise CommandError(
                    "Home Assistant is not configured (configure it in the UI Settings first), "
                    "or pass --demo / --no-ha-sync."
                )
            if not status_obj.reachable:
                raise CommandError(f"Home Assistant is not reachable: {status_obj.error or 'unknown error'}")

        now = timezone.now()
        with transaction.atomic():
            _delete_all_seed_data()

            alarm_system = AlarmSystem.objects.create(
                name="Test Home",
                timezone=getattr(settings, "TIME_ZONE", "UTC"),
            )
            primary_profile = _ensure_active_settings_profile()
            secondary_profile = _ensure_secondary_profile() if demo_mode else None
            get_current_snapshot(process_timers=False)

            admin_user = User.objects.create_superuser(
                email="admin@testhome.local",
                password="adminpass",
                timezone=getattr(settings, "TIME_ZONE", "UTC"),
                onboarding_completed_at=now,
            )
            _assign_role(user=admin_user, role_slug="admin")

            resident_user = User.objects.create_user(
                email="resident@testhome.local",
                password="residentpass",
                timezone=getattr(settings, "TIME_ZONE", "UTC"),
                onboarding_completed_at=now,
            )
            _assign_role(user=resident_user, role_slug="resident")

            guest_user = User.objects.create_user(
                email="guest@testhome.local",
                password="guestpass",
                timezone=getattr(settings, "TIME_ZONE", "UTC"),
                onboarding_completed_at=now,
            )
            _assign_role(user=guest_user, role_slug="guest")

            service_user = User.objects.create_user(
                email="service@testhome.local",
                password="servicepass",
                timezone=getattr(settings, "TIME_ZONE", "UTC"),
                onboarding_completed_at=now,
            )
            _assign_role(user=service_user, role_slug="service")

            allowed_all = [
                UserCodeAllowedState.AlarmState.DISARMED,
                UserCodeAllowedState.AlarmState.ARMED_HOME,
                UserCodeAllowedState.AlarmState.ARMED_AWAY,
                UserCodeAllowedState.AlarmState.ARMED_NIGHT,
                UserCodeAllowedState.AlarmState.ARMED_VACATION,
                UserCodeAllowedState.AlarmState.PENDING,
                UserCodeAllowedState.AlarmState.TRIGGERED,
            ]

            _create_code(
                user=admin_user,
                label="[seed] Admin PIN",
                raw_code="1234",
                code_type=UserCode.CodeType.PERMANENT,
                allowed_states=allowed_all,
            )
            _create_code(
                user=resident_user,
                label="[seed] Resident PIN",
                raw_code="2468",
                code_type=UserCode.CodeType.PERMANENT,
                allowed_states=allowed_all,
            )
            _create_code(
                user=guest_user,
                label="[seed] Guest temporary PIN",
                raw_code="1357",
                code_type=UserCode.CodeType.TEMPORARY,
                allowed_states=[
                    UserCodeAllowedState.AlarmState.ARMED_AWAY,
                    UserCodeAllowedState.AlarmState.ARMED_HOME,
                    UserCodeAllowedState.AlarmState.DISARMED,
                ],
            )

            if demo_mode:
                _create_code(
                    user=service_user,
                    label="[demo] Service one-time",
                    raw_code="909090",
                    code_type=UserCode.CodeType.ONE_TIME,
                    allowed_states=[UserCodeAllowedState.AlarmState.DISARMED],
                    max_uses=1,
                    start_at=now,
                    end_at=now + timedelta(days=1),
                )

            imported = updated = 0
            seen_entity_ids: set[str] = set()
            if not skip_ha_sync:
                imported, updated, seen_entity_ids = _sync_entities_from_home_assistant(now=now)

            if demo_mode:
                seen_entity_ids = _seed_demo_entities(now=now)
                tags = _seed_entity_tags()
                _apply_entity_tags(tags)
                _seed_demo_sensors(list(seen_entity_ids))
                _seed_demo_rules(admin_user=admin_user)
                _enable_demo_integrations(profile=primary_profile)
                _seed_notification_providers(profile=primary_profile)
                if secondary_profile is not None:
                    _seed_notification_providers(profile=secondary_profile)
                _seed_door_codes(
                    residents=[resident_user, admin_user, guest_user],
                    now=now,
                )
                _seed_control_panel()
                _seed_alarm_event_history(now=now, admin_user=admin_user)
                _seed_frigate_detections(now=now)
            else:
                required_entity_ids = {config.entry_entity_id, config.motion_entity_id, *config.extra_entity_ids}
                if required_entity_ids - seen_entity_ids:
                    missing = sorted(required_entity_ids - seen_entity_ids)
                    raise CommandError(
                        "Some configured entity_ids were not found in Home Assistant states: " + ", ".join(missing)
                    )

                Sensor.objects.create(
                    name="[seed] Entry Door",
                    entity_id=config.entry_entity_id,
                    is_active=True,
                    is_entry_point=True,
                )
                Sensor.objects.create(
                    name="[seed] Motion",
                    entity_id=config.motion_entity_id,
                    is_active=True,
                    is_entry_point=False,
                )

                rules: list[tuple[str, str, dict[str, Any]]] = [
                    (
                        "[seed] Trigger on entry open",
                        "trigger",
                        {
                            "when": {
                                "op": "entity_state",
                                "entity_id": config.entry_entity_id,
                                "equals": "on",
                            },
                            "then": [{"type": "alarm_trigger"}],
                        },
                    ),
                    (
                        "[seed] Trigger if motion stays on 5s",
                        "trigger",
                        {
                            "when": {
                                "op": "for",
                                "seconds": 5,
                                "child": {
                                    "op": "entity_state",
                                    "entity_id": config.motion_entity_id,
                                    "equals": "on",
                                },
                            },
                            "then": [{"type": "alarm_trigger"}],
                        },
                    ),
                ]

                for name, kind, definition in rules:
                    rule = Rule.objects.create(
                        name=name,
                        kind=kind,
                        enabled=True,
                        priority=10,
                        schema_version=1,
                        definition=definition,
                        cooldown_seconds=15,
                        created_by=admin_user,
                    )
                    for entity_id in {config.entry_entity_id, config.motion_entity_id}:
                        entity = Entity.objects.filter(entity_id=entity_id).first()
                        if entity:
                            RuleEntityRef.objects.get_or_create(rule=rule, entity=entity)

        self.stdout.write(self.style.SUCCESS("Seeded demo home successfully."))
        self.stdout.write(f"- Home: {alarm_system.name}")
        self.stdout.write(f"- Mode: {'demo (synthetic dataset)' if demo_mode else 'standard (HA-backed)'}")
        if not demo_mode:
            self.stdout.write(f"- HA base_url: {status_obj.base_url or '(not configured)'}")
            self.stdout.write(f"- Entities synced: imported={imported} updated={updated}")
            self.stdout.write(f"- Entry entity: {config.entry_entity_id}")
            self.stdout.write(f"- Motion entity: {config.motion_entity_id}")
        else:
            self.stdout.write(f"- Entities seeded: {len(seen_entity_ids)}")
            self.stdout.write(f"- Sensors: {Sensor.objects.count()}")
            self.stdout.write(f"- Rules: {Rule.objects.count()}")
            self.stdout.write(f"- Notification providers: {NotificationProvider.objects.count()}")
            self.stdout.write(f"- Door codes: {DoorCode.objects.count()}")
            self.stdout.write(f"- Control panels: {ControlPanelDevice.objects.count()}")
            self.stdout.write(f"- Alarm events: {AlarmEvent.objects.count()}")
            self.stdout.write(f"- Frigate detections: {FrigateDetection.objects.count()}")

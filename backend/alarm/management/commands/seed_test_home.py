from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from accounts.models import Role, User, UserCode, UserCodeAllowedState, UserRoleAssignment
from alarm import services
from integrations_home_assistant import api as home_assistant
from alarm.models import (
    AlarmSettingsProfile,
    AlarmState,
    AlarmSystem,
    Entity,
    Rule,
    RuleActionLog,
    RuleEntityRef,
    RuleRuntimeState,
    Sensor,
)


@dataclass(frozen=True)
class SeedEntitiesConfig:
    entry_entity_id: str
    motion_entity_id: str
    extra_entity_ids: list[str]


def _load_entities_config(path: Path) -> SeedEntitiesConfig:
    """Load the seed entities config JSON file and validate its shape."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except FileNotFoundError as exc:
        raise CommandError(f"Entities config file not found: {path}") from exc
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
    return AlarmSettingsProfile.objects.create(
        name="Default",
        is_active=True,
        delay_time=60,
        arming_time=60,
        trigger_time=120,
        disarm_after_trigger=False,
        code_arm_required=True,
        available_arming_states=[
            AlarmState.ARMED_AWAY,
            AlarmState.ARMED_HOME,
            AlarmState.ARMED_NIGHT,
            AlarmState.ARMED_VACATION,
        ],
        state_overrides={},
        audio_visual_settings={
            "beep_enabled": True,
            "countdown_display_enabled": True,
            "color_coding_enabled": True,
        },
        sensor_behavior={
            "warn_on_open_sensors": True,
            "auto_bypass_enabled": False,
            "force_arm_enabled": True,
        },
    )


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
) -> UserCode:
    """Create a `UserCode` and its allowed states."""
    code = UserCode.objects.create(
        user=user,
        code_hash=make_password(raw_code),
        label=label,
        code_type=code_type,
        pin_length=len(raw_code),
        is_active=True,
        max_uses=None,
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


def _delete_all_seed_data() -> None:
    """Destructively delete app data to reset the DB before seeding."""
    RuleEntityRef.objects.all().delete()
    RuleRuntimeState.objects.all().delete()
    RuleActionLog.objects.all().delete()
    Rule.objects.all().delete()
    Sensor.objects.all().delete()
    Entity.objects.all().delete()

    # Alarm state/events/settings
    from alarm.models import AlarmEvent, AlarmStateSnapshot

    AlarmEvent.objects.all().delete()
    AlarmStateSnapshot.objects.all().delete()
    AlarmSettingsProfile.objects.all().delete()
    AlarmSystem.objects.all().delete()

    # Accounts
    from rest_framework.authtoken.models import Token

    Token.objects.all().delete()
    UserCodeAllowedState.objects.all().delete()
    UserCode.objects.all().delete()
    UserRoleAssignment.objects.all().delete()
    User.objects.all().delete()


class Command(BaseCommand):
    help = "Destructively seed the database with a demo home, users, codes, entities, sensors, and rules."

    def add_arguments(self, parser):
        """Register CLI arguments for the seed command."""
        parser.add_argument(
            "--entities-file",
            default="schema/seed_entities.json",
            help="Path to JSON file specifying which HA entities to use for sensors/rules.",
        )
        parser.add_argument(
            "--no-ha-sync",
            action="store_true",
            help="Skip syncing entities from Home Assistant (still seeds users/codes/rules).",
        )

    def handle(self, *args, **options):
        """Seed the database with a demo home dataset (destructive)."""
        entities_file = Path(options["entities_file"]).expanduser()
        if not entities_file.is_absolute():
            entities_file = Path.cwd() / entities_file

        config = _load_entities_config(entities_file)
        if not config.entry_entity_id or not config.motion_entity_id:
            raise CommandError(
                f"Missing entity IDs in {entities_file}. Set both "
                f"`entry_entity_id` and `motion_entity_id` to real Home Assistant entity_ids."
            )

        status_obj = home_assistant.get_status()
        if not options["no_ha_sync"]:
            if not status_obj.configured:
                raise CommandError(
                    "Home Assistant is not configured (configure it in the UI Settings first)."
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
            _ensure_active_settings_profile()
            services.get_current_snapshot(process_timers=False)

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

            imported = updated = 0
            seen_entity_ids: set[str] = set()
            if not options["no_ha_sync"]:
                imported, updated, seen_entity_ids = _sync_entities_from_home_assistant(now=now)

            required_entity_ids = {config.entry_entity_id, config.motion_entity_id, *config.extra_entity_ids}
            if not options["no_ha_sync"] and required_entity_ids - seen_entity_ids:
                missing = sorted(required_entity_ids - seen_entity_ids)
                raise CommandError(
                    "Some configured entity_ids were not found in Home Assistant states: "
                    + ", ".join(missing)
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
        self.stdout.write(f"- HA base_url: {status_obj.base_url or '(not configured)'}")
        self.stdout.write(f"- Entities synced: imported={imported} updated={updated}")
        self.stdout.write(f"- Entry entity: {config.entry_entity_id}")
        self.stdout.write(f"- Motion entity: {config.motion_entity_id}")

from __future__ import annotations

from rest_framework import serializers

from alarm.models import Rule, RuleEntityRef
from alarm.rules.action_schemas import ADMIN_ONLY_ACTION_TYPES, validate_action
from alarm.use_cases.rule_entity_refs import sync_rule_entity_refs


class RuleSerializer(serializers.ModelSerializer):
    entity_ids = serializers.SerializerMethodField()

    class Meta:
        model = Rule
        fields = (
            "id",
            "name",
            "kind",
            "enabled",
            "priority",
            "schema_version",
            "definition",
            "cooldown_seconds",
            "created_by",
            "created_at",
            "updated_at",
            "entity_ids",
        )

    def get_entity_ids(self, obj: Rule) -> list[str]:
        """Return referenced entity_ids, preferring serializer context/prefetch for performance."""
        entity_ids_by_rule_id = self.context.get("entity_ids_by_rule_id")
        if isinstance(entity_ids_by_rule_id, dict):
            value = entity_ids_by_rule_id.get(obj.id)
            if isinstance(value, (list, tuple, set)):
                return sorted({str(x) for x in value if str(x).strip()})

        prefetched = getattr(obj, "_prefetched_objects_cache", {}) or {}
        if "entity_refs" in prefetched:
            entity_ids: set[str] = set()
            for ref in obj.entity_refs.all():
                entity = getattr(ref, "entity", None)
                entity_id = getattr(entity, "entity_id", "") if entity is not None else ""
                entity_id = (entity_id or "").strip()
                if entity_id:
                    entity_ids.add(entity_id)
            return sorted(entity_ids)

        return list(
            RuleEntityRef.objects.filter(rule=obj)
            .select_related("entity")
            .values_list("entity__entity_id", flat=True)
        )


def derive_kind_from_actions(definition: dict) -> str:
    """Derive rule kind from the first action in the then clause."""
    then_actions = definition.get("then", []) if isinstance(definition, dict) else []
    if not then_actions:
        return "trigger"  # Default

    first_action = then_actions[0] if isinstance(then_actions, list) else {}
    action_type = first_action.get("type", "") if isinstance(first_action, dict) else ""

    # Map action types to rule kinds
    if action_type == "alarm_trigger":
        return "trigger"
    elif action_type == "alarm_disarm":
        return "disarm"
    elif action_type == "alarm_arm":
        return "arm"
    else:
        return "trigger"  # Default for ha_call_service, zwavejs_set_value, etc.


class RuleUpsertSerializer(serializers.ModelSerializer):
    entity_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
    )
    # kind is auto-derived from actions, not required in input
    kind = serializers.CharField(required=False)

    class Meta:
        model = Rule
        fields = (
            "id",
            "name",
            "kind",
            "enabled",
            "priority",
            "schema_version",
            "definition",
            "cooldown_seconds",
            "entity_ids",
        )

    def validate_definition(self, value):
        """Validate the rule definition schema, including THEN action validation."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("definition must be an object.")

        # Validate "then" actions if present
        then_actions = value.get("then")
        if then_actions is not None:
            if not isinstance(then_actions, list):
                raise serializers.ValidationError({"then": "must be a list of actions"})

            schema_version = self.initial_data.get("schema_version", 1)
            for i, action in enumerate(then_actions):
                errors = validate_action(action, schema_version)
                if errors:
                    raise serializers.ValidationError({"then": {i: errors}})

        return value

    def validate(self, attrs):
        """Enforce admin privileges for admin-only action types."""
        # Check permissions for admin-only action types
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None

        definition = attrs.get("definition", {})
        then_actions = definition.get("then", []) if isinstance(definition, dict) else []

        for action in then_actions:
            if not isinstance(action, dict):
                continue
            action_type = action.get("type")
            if action_type in ADMIN_ONLY_ACTION_TYPES:
                if not user or not getattr(user, "is_staff", False):
                    raise serializers.ValidationError({
                        "definition": {
                            "then": f"Action type '{action_type}' requires admin privileges"
                        }
                    })

        return attrs

    def validate_entity_ids(self, value: list[str]) -> list[str]:
        """Normalize and validate entity ids, ensuring they have a domain prefix."""
        cleaned: list[str] = []
        for raw in value:
            entity_id = (raw or "").strip()
            if not entity_id:
                continue
            if "." not in entity_id:
                raise serializers.ValidationError(f"Invalid entity_id: {entity_id}")
            cleaned.append(entity_id)
        return sorted(set(cleaned))

    def create(self, validated_data):
        """Create a rule and sync its entity refs. Auto-derives kind from actions."""
        entity_ids = validated_data.pop("entity_ids", None)

        # Auto-derive kind from actions if not provided
        definition = validated_data.get("definition", {})
        if "kind" not in validated_data or not validated_data.get("kind"):
            validated_data["kind"] = derive_kind_from_actions(definition)

        # Auto-extract entity_ids from definition if not explicitly provided (ADR 0057)
        if entity_ids is None:
            from alarm.dispatcher.entity_extractor import extract_entity_ids_from_definition
            entity_ids = list(extract_entity_ids_from_definition(definition))

        rule = super().create(validated_data)
        sync_rule_entity_refs(rule=rule, entity_ids=entity_ids)

        # Invalidate dispatcher cache so new rule triggers immediately (ADR 0057)
        from alarm.dispatcher import invalidate_entity_rule_cache
        invalidate_entity_rule_cache()

        return rule

    def update(self, instance, validated_data):
        """Update a rule and sync its entity refs. Auto-derives kind from actions."""
        entity_ids = validated_data.pop("entity_ids", None)

        # Auto-derive kind from actions if not provided
        definition = validated_data.get("definition", instance.definition)
        if "kind" not in validated_data or not validated_data.get("kind"):
            validated_data["kind"] = derive_kind_from_actions(definition)

        rule = super().update(instance, validated_data)

        # Auto-extract entity_ids from definition if not explicitly provided and definition changed (ADR 0057)
        if entity_ids is None and "definition" in validated_data:
            from alarm.dispatcher.entity_extractor import extract_entity_ids_from_definition
            entity_ids = list(extract_entity_ids_from_definition(definition))

        if entity_ids is not None:
            sync_rule_entity_refs(rule=rule, entity_ids=entity_ids)
            # Invalidate dispatcher cache so updated rule triggers immediately (ADR 0057)
            from alarm.dispatcher import invalidate_entity_rule_cache
            invalidate_entity_rule_cache()

        return rule

from __future__ import annotations

from alarm.models import Entity, Rule, RuleEntityRef


def sync_rule_entity_refs(*, rule: Rule, entity_ids: list[str]) -> None:
    """Sync a rule's referenced entities from a list of entity_id strings."""
    entities: list[Entity] = []
    for entity_id in entity_ids:
        domain = entity_id.split(".", 1)[0]
        entity, _ = Entity.objects.get_or_create(
            entity_id=entity_id,
            defaults={
                "domain": domain,
                "name": entity_id,
                "attributes": {},
            },
        )
        entities.append(entity)

    RuleEntityRef.objects.filter(rule=rule).exclude(entity__in=entities).delete()
    existing = set(
        RuleEntityRef.objects.filter(rule=rule, entity__in=entities).values_list(
            "entity_id", flat=True
        )
    )
    RuleEntityRef.objects.bulk_create(
        [RuleEntityRef(rule=rule, entity=e) for e in entities if e.id not in existing],
        ignore_conflicts=True,
    )

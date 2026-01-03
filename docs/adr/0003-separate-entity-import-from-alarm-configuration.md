# ADR 0003: Separate Entity Import from Alarm Configuration

## Status
Proposed

## Context
The current “Import Sensors” UI mixes multiple concerns:
- Importing Home Assistant entities (currently focused on `binary_sensor`).
- Assigning imported items into Zones.
- Marking whether an imported item is an “Entry sensor” (alarm behavior).

This is confusing because “importing” is a general integration step, while “alarm trigger configuration” is only one possible use of an entity. We want imported entities to be usable for multiple features (e.g., triggers, notifications, automations, dashboards), not just alarm triggers.

## Decision
- Introduce a dedicated “Import Entities” flow whose only job is to bring Home Assistant entities (all domains/types) into the app as reusable, first-class objects.
- Move alarm-specific configuration (zones, trigger behavior, entry/instant trigger, enabled/disabled) to separate pages that operate on imported entities.
- Keep the import flow reversible and safe (idempotent import by `entity_id`, clear “already imported” state, and bulk selection/search).

## Alternatives Considered
- Keep a single “Import Sensors” page and add more options/roles per entity (triggers, notifications, etc.).
- Keep the current flow but add more tooltips/wizard steps to explain zones and entry behavior.
- Split by domain-specific import pages (e.g., “Import binary_sensors”, “Import lights”, “Import cameras”).

## Consequences
- UX becomes clearer: “import” is integration; “configure” is feature-specific.
- Enables future features to reuse the same imported entities without duplicating import logic.
- Requires backend/API and schema adjustments to represent imported entities independently from alarm “Sensor” objects.
- Requires migration/refactor of the existing `Sensor.entity_id` mapping into the new entity registry model (or a compatible abstraction).
- Routes/navigation and permissions need to reflect the two-step flow (Import → Configure).

## Todos
- Define the imported-entity data model (e.g., `Entity` with unique `entity_id`, `domain`, `name`, `device_class`, raw metadata, timestamps).
- Decide how “alarm sensors” relate to imported entities (e.g., `Sensor` references `Entity`, or `Sensor` becomes an “AlarmTrigger” config record).
- Add API endpoints for entity import/listing/search and for alarm trigger configuration.
- Refactor frontend routes: “Import Entities” page + “Alarm Triggers” page + “Zone Management” page (or similar).
- Migrate existing imported sensors so no users lose configuration.
- Decide how to handle de-duplication, refresh/sync behavior, and “entity disappeared” states.

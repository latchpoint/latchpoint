# ADR 0048: User-Friendly Zigbee2MQTT Mappings Editor

## Status
Superseded by ADR 0049

## Context
The current Zigbee2MQTT settings UI exposes mappings primarily as raw JSON arrays with minimal affordances:
- A “quick add” form exists, but it only covers common cases and still requires users to understand/verify the resulting JSON.
- Editing raw JSON is error-prone (syntax mistakes, wrong keys, wrong state names) and unfriendly on mobile.
- Users cannot easily see/modify existing mappings as “items” (add/edit/delete) without manual JSON surgery.
- Users often don’t know the exact `friendly_name` / available `action` strings, even though the app already syncs Zigbee2MQTT devices.

Zigbee2MQTT mappings are a core integration surface and should be approachable for admins without requiring JSON literacy, while still keeping an “escape hatch” for advanced workflows.

## Decision
Implement a guided, form-based mappings editor that:
- Treats mappings as first-class list items (create/edit/delete, reorder as needed).
- Uses data from synced Zigbee2MQTT devices to help users choose targets (`friendly_name`, optionally `ieee_address`) instead of typing free-form strings.
- Provides structured inputs for:
  - **Input mappings**: target device, one-or-more action names, and alarm action (including arm mode).
  - **Output mappings**: target device, optional topic override, and per-alarm-state payload builder.
- Performs immediate client-side validation with clear, field-level errors (mirroring backend serializer rules).
- Keeps an “Advanced” toggle to view/edit the raw JSON arrays directly, with round-trip conversion between the structured editor state and JSON.

## Alternatives Considered
- Keep the current approach (raw JSON + quick-add).
  - Simple to maintain, but continues to be error-prone and not discoverable.
- Replace `<textarea>` with a JSON editor (Monaco/CodeMirror) + schema hints.
  - Improves syntax, but still requires users to understand the mapping schema and doesn’t solve discoverability of devices/actions.
- Move mapping authoring to YAML files and import/export.
  - Adds operational complexity and doesn’t improve day-to-day UI editing.

## Consequences
- More frontend code and UI complexity (state management, validation, conversions).
- Requires careful “source of truth” handling to avoid losing user edits when switching between guided/advanced modes.
- Better UX: fewer invalid configs, faster setup, less time spent debugging typos.

## Todos
- Note: This ADR is superseded. The preferred direction is to make Zigbee2MQTT entity-first and drive behavior through the rules engine, rather than maintaining a separate mappings schema/UX.
- Prereqs / constraints (ADR 0040 implemented)
  - Treat backend serializers as the source of truth; client-side validation is for fast feedback only.
  - Assume alarm-control execution semantics (use-cases/audit/rate limiting) are stable; this ADR focuses on authoring mappings.
  - Do not require a separate “validate-only” endpoint; optionally add one later if the UX still needs server-side draft validation.
- Frontend (execution plan)
  - Slice 0: foundations (low-risk, mergeable)
    - Add a guided mappings type + pure conversion helpers with round-trip tests.
    - Add JSON formatting + parse error UI to the existing textareas (even before the guided editor ships).
  - Slice 1: guided input mappings
    - Build list + add/edit/delete UI for input mappings (still backed by JSON serialization on save).
    - Keep the existing quick-add as a shortcut that creates an input mapping item in the guided state.
  - Slice 2: guided output mappings
    - Build list + add/edit/delete UI for output mappings (payloads-by-state builder).
    - Replace “Upsert output mapping” with explicit add/edit flows (upsert becomes “Save mapping” on a selected item).
  - Slice 3: advanced mode + edge cases
    - Implement a robust “Advanced JSON” toggle with safe import/export, conversion warnings, and “discard/keep” prompts.
    - Add mapping duplication, bulk delete, and optional reorder if users request it.
  - UX structure
    - Split the current “Mappings (advanced)” card into:
      - “Input mappings” (list + editor)
      - “Output mappings” (list + editor)
      - “Advanced JSON” (collapsed by default)
    - Keep the existing quick-add forms as “templates” inside the guided UI, or replace with “Add mapping” dialogs that prefill fields.
  - Data model (client-side)
    - Define a typed “guided” representation that mirrors backend schema:
      - Input mapping: `{ target: { friendly_name?; ieee_address? }, actions: string[], alarm_action: 'disarm'|'cancel_arming'|'arm', arm_mode?: <armed state> }`
      - Output mapping: `{ target: { friendly_name?; ieee_address? }, topic?: string, payloads_by_state: Record<AlarmState, object> }`
    - Add deterministic conversion helpers:
      - `parseGuidedFromJson(inputMappingsJson, outputMappingsJson) -> guided state + non-fatal warnings`
      - `serializeGuidedToJson(guided state) -> { inputMappingsJson, outputMappingsJson }` (pretty-printed, stable ordering)
    - Track an “unsaved changes” flag and protect mode switches with confirm dialogs when conversion would drop/alter data.
  - Guided editor UI
    - Input mappings list
      - Render each mapping as a row/card with: target (friendly/ieee), actions count, alarm action summary, and edit/delete buttons.
      - Provide “Add input mapping” and “Duplicate” actions.
    - Input mapping editor
      - Target picker:
        - Dropdown/autocomplete backed by synced devices (use `devicesQuery.data`).
        - Fallback: manual text inputs for `friendly_name` / `ieee_address`.
      - Actions input:
        - Start with tag input (comma/enter to add).
        - Optional enhancement: show recent/known actions per selected device if available; otherwise provide common suggestions.
      - Alarm action selector:
        - Dropdown for `disarm` / `cancel_arming` / `arm`.
        - When `arm`, show arm mode dropdown.
    - Output mappings list
      - Render each mapping as: target + state keys present + topic override indicator, with edit/delete buttons.
      - Provide “Add output mapping” and “Duplicate” actions.
    - Output mapping editor
      - Target picker (same as input).
      - Topic override:
        - Default blank => backend/runtime uses `${base_topic}/${friendly_name}/set` semantics (or current behavior).
      - Payloads-by-state builder:
        - Checklist of alarm states + “edit payload” per selected state.
        - Payload editor per state:
          - Start with JSON textarea (per-state) with format button.
          - Optional enhancement: key/value form builder for shallow objects (still stores JSON object).
  - Validation & error handling
    - Implement client-side validators that match backend serializer semantics:
      - Require at least one of `friendly_name` / `ieee_address` (allow both).
      - Input `actions`: non-empty list of non-empty strings.
      - Output `payloads_by_state`: non-empty object; keys must be valid alarm states.
      - `alarm_action`: enforce `arm:<state>` mapping when serializing (or keep separate fields until serialization).
    - Display field-level errors inside the mapping editor and prevent saving when invalid.
    - On save, if backend rejects mappings, map DRF errors back to the corresponding mapping item (by index) and show a targeted message.
  - Advanced JSON mode (escape hatch)
    - Keep raw JSON textareas, but:
      - Add “Format JSON” buttons and show parse errors inline.
      - Add “Import from JSON” -> populates guided editor (with warnings list).
      - Add “Edit as JSON” toggle; when leaving advanced mode, attempt parse+convert and confirm on warnings/drops.
  - Integration with existing settings model
    - Update `useZigbee2mqttSettingsModel` to store guided state alongside `inputMappingsJson` / `outputMappingsJson`, or switch the draft source of truth to guided state and derive JSON on save.
    - Preserve current behavior for quick add operations (either update guided state or keep them as shortcuts that create guided entries).
  - Tests
    - Unit tests for conversion helpers and validators (round-trip, stable formatting, edge cases).
    - Component tests for add/edit/delete flows (if the frontend test harness exists in this repo).
- Backend (optional / follow-up)
  - Serializer ergonomics
    - Ensure nested/`many=True` validation errors preserve list indices so the UI can attach messages to the right mapping row.
    - (Optional) Add a `POST /api/alarm/integrations/zigbee2mqtt/validate/` endpoint if we need server-side draft validation without saving.
  - Discoverability improvements
    - If feasible, expose per-device “known actions” metadata (or last-seen actions) from Zigbee2MQTT ingest to improve the actions picker.
  - Documentation
    - Add a short “How to create mappings” doc page and link it from the settings tab.

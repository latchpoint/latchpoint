# ADR 0034: Home Assistant Notifications as Rule Actions

## Status
**Superseded by ADR 0044**

## Context
Currently, Home Assistant notifications are configured in the Settings > Notifications tab. This approach has limitations:

1. **Limited trigger conditions**: Notifications can only be triggered by alarm state changes (e.g., TRIGGERED, ARMED_AWAY). Users cannot send notifications based on entity states, Frigate person detection, or other rule conditions.

2. **Single notification configuration**: The settings approach allows only one notification service configuration with a single cooldown, applied uniformly to all selected states.

3. **Separation from automation logic**: Notifications are configured separately from the rules that define alarm behavior, making it harder to understand the complete automation flow.

4. **Inconsistent with rules architecture**: ADR 0021 established the rules engine as the "complete IF/THEN automation surface," but notifications remain outside this pattern.

The current settings-based notification structure:
```python
{
  "enabled": False,
  "service": "notify.notify",
  "cooldown_seconds": 0,
  "states": []  # List of alarm states that trigger notifications
}
```

This is essentially a simplified rule: "IF alarm state changes to X, THEN call notify service" — which is already expressible using the existing `ha_call_service` action.

## Decision
We leverage the existing `ha_call_service` action type (ADR 0021) for notifications and deprecate the Settings > Notifications tab. The rules builder already supports calling Home Assistant services, so notifications are just a specific use case of `ha_call_service` with `notify.*` services.

> **Note**: During investigation for this ADR, we discovered that the frontend and backend have diverged on the `ha_call_service` schema. The backend correctly uses the `action` field (matching Home Assistant 2024.8+ terminology), while the frontend still uses legacy `domain`/`service` fields. This must be fixed as a prerequisite to this work. See "Frontend/Backend alignment required" section below.

### Using existing `ha_call_service` for notifications

Notifications use the existing action schema:
```json
{
  "type": "ha_call_service",
  "action": "notify.mobile_app_iphone",
  "data": {
    "message": "Alarm triggered!",
    "title": "Security Alert"
  }
}
```

This already works today with no backend changes required.

### Frontend/Backend alignment required

There is currently a mismatch between frontend and backend schemas:

- **Backend** (`action_schemas.py`): Uses `action` field with `domain.action` format
  ```json
  {"type": "ha_call_service", "action": "notify.notify", "data": {...}}
  ```
  This aligns with Home Assistant 2024.8+ "actions" terminology.

- **Frontend** (`ruleDefinition.ts`): Uses separate `domain` + `service` fields
  ```json
  {"type": "ha_call_service", "domain": "notify", "service": "notify", "service_data": {...}}
  ```
  This is the legacy format.

**Resolution**: Update frontend types and UI to use the `action` field format, matching the backend and HA's current terminology. This is a prerequisite for this ADR.

### Frontend enhancements

To improve the UX for notifications specifically, we add frontend affordances:

1. **Notification-specific action template**: Add "Send Notification" as a preset in the action type picker that pre-fills `ha_call_service` with `notify.*` pattern

2. **Notify service picker**: When action is `notify.*`, show the existing `HomeAssistantNotifyServicesPicker` component instead of a generic text field

3. **Structured data editor**: For notify actions, show dedicated `message` and `title` fields instead of raw JSON data editor

4. **Action presets/templates**: Quick-add buttons for common patterns:
   - "Notify on trigger" — pre-configured rule template
   - "Notify on arm/disarm" — pre-configured rule template

### Remove Settings > Notifications tab

Since notifications are now configured via rules:

1. Remove `SettingsNotificationsTab.tsx` and related components
2. Remove `home_assistant_notify` from `ALARM_PROFILE_SETTINGS`
3. Remove `useNotificationsSettingsModel.ts` hook

### Migration path

1. **Automatic migration**: On upgrade, create rules from existing notification settings:
   - For each state in `home_assistant_notify.states`, create a rule:
     - Name: `Notify on {state}` (e.g., "Notify on TRIGGERED")
     - Kind: `trigger` (or new `notify` kind if desired)
     - When: `{"type": "alarm_state_in", "states": ["{state}"]}`
     - Then: `[{"type": "ha_call_service", "action": "{service}", "data": {"message": "Alarm is now {state}", "title": "Alarm Notification"}}]`
     - Cooldown: Use existing `cooldown_seconds`

2. **Mark old setting as migrated**: Set `home_assistant_notify.migrated = true` to prevent re-migration

3. **Remove settings entry**: In a future release, remove `home_assistant_notify` from `ALARM_PROFILE_SETTINGS`

### Example rules

**Notify when alarm triggers:**
```json
{
  "when": {"type": "alarm_state_in", "states": ["triggered"]},
  "then": [
    {
      "type": "ha_call_service",
      "action": "notify.mobile_app_iphone",
      "data": {
        "message": "Security alarm triggered!",
        "title": "ALARM TRIGGERED",
        "data": {"push": {"sound": "alarm.caf", "interruption-level": "critical"}}
      }
    }
  ]
}
```

**Notify when person detected while armed:**
```json
{
  "when": {
    "type": "all",
    "conditions": [
      {"type": "alarm_state_in", "states": ["armed_away", "armed_home"]},
      {"type": "frigate_person_detected", "min_score": 0.7}
    ]
  },
  "then": [
    {
      "type": "ha_call_service",
      "action": "notify.notify",
      "data": {
        "message": "Person detected while alarm is armed",
        "title": "Person Detected"
      }
    }
  ]
}
```

**Notify when door left open:**
```json
{
  "when": {
    "type": "for",
    "seconds": 300,
    "condition": {"type": "entity_state", "entity_id": "binary_sensor.front_door", "state": "on"}
  },
  "then": [
    {
      "type": "ha_call_service",
      "action": "notify.notify",
      "data": {"message": "Front door has been open for 5 minutes"}
    }
  ]
}
```

## Alternatives Considered

1. **Keep notifications in settings, add rules option**
   - Rejected: Creates two ways to do the same thing, confusing UX
   - Maintaining both systems doubles implementation/testing effort

2. **Add dedicated `ha_notify` action type**
   - Rejected: `ha_call_service` already handles this use case
   - Would add redundant code and schema validation
   - Frontend UX improvements achieve the same goal without backend changes

3. **Generic "notification" action with provider abstraction**
   - Considered for future: Could support push, SMS, email, webhooks
   - Rejected for now: Over-engineering; HA notify covers most use cases
   - Can add new action types later if needed

## Consequences

### Positive
- Notifications become a first-class part of the rules system
- Users can trigger notifications on any condition, not just alarm state changes
- Multiple notification rules with different services/messages/cooldowns
- Consistent mental model: all automation in the rules builder
- Better auditability: notification sends logged in rule action logs
- **No backend changes required** — just frontend UX and migration

### Negative
- Breaking change: existing notification settings need migration
- Slightly more complex initial setup (create a rule vs. toggle + pick states)
- Users familiar with old UI need to learn rules builder

### Neutral
- Removes one settings tab
- Documentation needs updating

## Implementation Plan

1. **Prerequisite: Align frontend with HA actions terminology**
   - [x] Update `HaCallServiceAction` interface to use `action` field instead of `domain`/`service`
   - [x] Update `ruleDefinition.ts` type guards
   - [x] Update `ActionsEditor.tsx` to use `action` field
   - [x] Update any converters/hydrators that transform action data

2. **Frontend notification UX**
   - [x] Add "Send Notification" preset to action type picker
   - [x] Add notify service picker when action matches `notify.*`
   - [x] Add structured message/title fields for notify actions
   - [x] Remove `SettingsNotificationsTab` and related components
   - [ ] Add notification rule templates to rules builder

3. **Backend**
   - [x] Add migration command to convert existing notification settings to rules
   - [x] Mark `home_assistant_notify` setting as deprecated
   - [x] Add tests for migration

4. **Cleanup**
   - [x] Remove `home_assistant_notify` from `ALARM_PROFILE_SETTINGS`
   - [ ] Update user documentation

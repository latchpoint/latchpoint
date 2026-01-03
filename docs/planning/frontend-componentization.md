# Frontend Componentization Planning

## Goal

Reduce page-level complexity by extracting repeatable UI + state patterns into reusable, feature-scoped components and hooks. Intended outcome: thinner route components, less duplicated logic, and more consistent UX across settings/setup/admin flows.

This is a refactor plan (no behavior changes intended).

## Status (implemented)

Completed extractions:
- Settings tabs/setup: `frontend/src/features/settings/components/SettingsTabShell.tsx`, `frontend/src/features/settings/hooks/useDraftFromQuery.ts`, `frontend/src/lib/numberParsers.ts`
- Integration settings tab decomposition:
  - Zigbee2MQTT: `frontend/src/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel.ts` + `frontend/src/features/zigbee2mqtt/components/*`
  - MQTT: `frontend/src/features/mqtt/hooks/useMqttSettingsModel.ts` + `frontend/src/features/mqtt/components/MqttSettingsCard.tsx`
  - Home Assistant: `frontend/src/features/homeAssistant/hooks/useHomeAssistantSettingsModel.ts` + `frontend/src/features/homeAssistant/components/*`
  - Notifications: `frontend/src/features/notifications/hooks/useNotificationsSettingsModel.ts` + `frontend/src/features/notifications/components/*`
  - Frigate: `frontend/src/features/frigate/hooks/useFrigateSettingsModel.ts` + `frontend/src/features/frigate/components/*`
  - Alarm settings: `frontend/src/features/alarmSettings/hooks/useAlarmSettingsTabModel.ts` + `frontend/src/features/alarmSettings/components/*`
  - Z-Wave JS: `frontend/src/features/zwavejs/hooks/useZwavejsSettingsModel.ts` + `frontend/src/features/zwavejs/components/*`
- Codes shared pieces: `frontend/src/features/codes/components/DaysOfWeekPicker.tsx`, `frontend/src/features/codes/components/ActiveWindowPicker.tsx`, `frontend/src/features/codes/components/TimeWindowFields.tsx`, `frontend/src/features/codes/utils/*`
- Door codes lock picking: `frontend/src/features/doorCodes/components/LockEntityPicker.tsx`
- Sensor import: `frontend/src/features/sensors/components/*` + `frontend/src/features/sensors/hooks/useImportSensorsModel.ts`
- Rules: `frontend/src/features/rules/builder.ts`, `frontend/src/features/rules/components/*` (including `RuleEditorCard`)
- Rules builder decomposition:
  - When rows: `frontend/src/features/rules/components/when/*`
  - Then rows: `frontend/src/features/rules/components/then/*`
  - Rule editor sections: `frontend/src/features/rules/components/editor/*`
  - Page helpers: `frontend/src/features/rules/components/RulesPageActions.tsx`, `frontend/src/features/rules/components/RulesPageNotices.tsx`, `frontend/src/features/rules/utils/hydrateBuilderFromRule.ts`
- Rules page models: `frontend/src/features/rules/hooks/useRulesPageModel.ts`, `frontend/src/features/rulesTest/hooks/useRulesTestPageModel.ts`
- Rules test scenarios: `frontend/src/features/rulesTest/scenarios.ts`, `frontend/src/features/rulesTest/components/ScenarioRowsEditor.tsx`
- Integration connection/status UI: `frontend/src/features/integrations/components/ConnectionStatus.tsx`, `frontend/src/features/integrations/components/BooleanStatusPill.tsx`
- Setup wizard alerts: `frontend/src/features/settings/components/AdminActionRequiredAlert.tsx`
- Arm state selection UI: `frontend/src/features/codes/components/AllowedArmStatesPicker.tsx`
- Setup pages feature modules:
  - MQTT: `frontend/src/features/setupMqtt/hooks/useSetupMqttModel.ts` + `frontend/src/features/setupMqtt/components/SetupMqttCard.tsx`
  - Z-Wave JS: `frontend/src/features/setupZwavejs/hooks/useSetupZwavejsModel.ts` + `frontend/src/features/setupZwavejs/components/SetupZwavejsCard.tsx`
  - Setup wizard: `frontend/src/features/setupWizard/hooks/useSetupWizardModel.ts` + `frontend/src/features/setupWizard/components/SetupWizardCard.tsx`
- Events page feature module: `frontend/src/features/events/hooks/useEventsPageModel.ts` + `frontend/src/features/events/components/*`
- Shared re-auth password field: `frontend/src/features/codes/components/ReauthPasswordField.tsx`
- Door code helpers: `frontend/src/features/doorCodes/utils/maxUses.ts`
- Door codes UI: `frontend/src/features/doorCodes/components/DoorCodeCreateForm.tsx`, `frontend/src/features/doorCodes/components/DoorCodeEditPanel.tsx`
- Door codes page decomposition: `frontend/src/features/doorCodes/components/DoorCodeCreateCard.tsx`, `frontend/src/features/doorCodes/components/DoorCodeEditContainer.tsx`, `frontend/src/features/doorCodes/components/DoorCodeCard.tsx`, `frontend/src/features/doorCodes/components/DoorCodesTargetUserCard.tsx`

## Current hotspots

Largest route components (approx. LOC):
- `frontend/src/pages/DoorCodesPage.tsx` (~138)
- `frontend/src/pages/ImportSensorsPage.tsx` (~131)
- `frontend/src/pages/CodesPage.tsx` (~118)
- `frontend/src/pages/RulesTestPage.tsx` (~130)
- `frontend/src/pages/RulesPage.tsx` (~83)
- Settings tabs are now thin route wrappers (`~30–50` LOC each) with feature-scoped components/hooks.
 - Setup pages are now thin route wrappers (`~35` LOC each) with feature-scoped components/hooks.

Common cause: pages mixing orchestration (queries/mutations, draft syncing, validation, confirms) with rendering.

## Repeated patterns worth extracting

### 1) Settings tab shell (many tabs)

Repeated across settings tabs:
- admin gating banner (`Admin role required to change settings.`)
- local `error` / `notice` state + alert rendering
- draft initialization (`initialDraft` + `useEffect` with `prev ?? initial`)
- standard action clusters: Refresh / Reset / Save (plus Test/Sync/Publish variants)
- duplicated numeric parsing helpers (`parseIntField`, `parseFloatField`)

Targets:
- `frontend/src/pages/settings/SettingsMqttTab.tsx`
- `frontend/src/pages/settings/SettingsHomeAssistantTab.tsx`
- `frontend/src/pages/settings/SettingsZwavejsTab.tsx`
- `frontend/src/pages/settings/SettingsFrigateTab.tsx`
- `frontend/src/pages/settings/SettingsAlarmTab.tsx`
- `frontend/src/pages/settings/SettingsNotificationsTab.tsx`
- overlaps with setup pages: `frontend/src/pages/SetupMqttPage.tsx`, `frontend/src/pages/SetupZwavejsPage.tsx`

### 2) Integration status rendering (MQTT / HA / Z-Wave / Frigate / Zigbee2MQTT)

Common concepts:
- enabled/configured/connected/reachable
- last error + last timestamp patterns
- readiness gates (e.g., “MQTT must be enabled/configured” warnings)

Opportunity: shared components to keep wording and visual status consistent.

### 3) Codes + Door Codes shared helpers

Duplicate helper logic exists in both:
- datetime-local ⇄ ISO conversions
- days-of-week mask ⇄ Set conversions + formatting
- digit-only code validation rules (minor differences)

Both pages also implement similar UI patterns:
- create/edit forms
- date ranges + day-of-week selection + time windows
- repeated validation rule shapes

### 4) Rules builder is a single large module

`frontend/src/pages/RulesPage.tsx` includes:
- builder types + pure helper functions
- UI for multiple “row types” (conditions/actions)
- JSON editing + preview + persistence wiring

Natural boundaries exist for row components and pure utilities.

### 5) Import sensors has clean subcomponents

`frontend/src/pages/ImportSensorsPage.tsx` includes:
- toolbar (search + view mode)
- list/pagination (“Load more”)
- row UI (select, name override, entry point toggle/help)
- submit progress

All are separable, feature-scoped components.

## Proposed foldering (incremental)

Keep `components/ui/*` as generic primitives. Introduce feature modules for domain components:

- `frontend/src/features/settings/`
  - `components/SettingsTabShell.tsx`
  - `hooks/useDraftFromQuery.ts`
  - `utils/parsers.ts`
- `frontend/src/features/integrations/`
  - `components/IntegrationStatusPills.tsx`
  - `components/IntegrationReadinessAlert.tsx`
- `frontend/src/features/codes/`
  - `components/DaysOfWeekPicker.tsx`
  - `components/TimeWindowFields.tsx`
  - `utils/datetimeLocal.ts`
  - `utils/daysOfWeek.ts`
- `frontend/src/features/rules/`
  - `components/RuleEditor/*`
  - `utils/builder.ts`
- `frontend/src/features/sensors/`
  - `components/EntityImportToolbar.tsx`
  - `components/EntityImportList.tsx`
  - `components/EntityImportRow.tsx`

Pages remain route composition + data wiring; feature modules hold the complexity.

## Concrete extraction candidates (high ROI)

### A) `SettingsTabShell`

Wrapper for tabs to standardize:
- admin-only messaging
- load error vs local error vs notice alerts
- consistent spacing/layout

Sketch:
- `SettingsTabShell({ isAdmin, loadError, error, notice, children })`

Optional:
- `SettingsTabActions` for common Refresh/Reset/Save clusters.

### B) `useDraftFromQuery`

Encapsulate the “initialize draft once from query data” pattern:
- eliminates repeated `queueMicrotask` and `prev ?? initialDraft`
- supports `reset()` and optional “draft override” mode (needed for Zigbee2MQTT tab)

### C) Shared numeric parsing helpers

Unify duplicated implementations:
- `parseIntInRange(label, raw, { min, max })`
- `parseFloatInRange(label, raw, { min, max })`

Note: `frontend/src/pages/settings/settingsUtils.ts` already uses `{ ok, value | error }` helpers. Consider standardizing on that shape (instead of throwing) for consistent UX.

### D) Integration status components

Standardize across settings + setup:
- status pills (“Connected/Disconnected/Disabled”, “Reachable/Not reachable/Not configured”)
- last error line rendering
- readiness gates (MQTT required, etc.)

### E) Codes/Door Codes shared primitives

Extract shared utilities and UI:
- datetime-local conversion utils
- days-of-week mask/set utils + formatting
- `DaysOfWeekPicker`
- shared “time window start/end” fields + validation helper

### F) Rules page modularization

Split into:
- `RuleList` (list + select/edit)
- `RuleEditor` (builder + JSON editor)
- `ConditionBuilder` and `ActionBuilder` with row components per type

Move pure transformations to `features/rules/utils/builder.ts` (easier to reason about and test).

### G) Import sensors feature components

Extract:
- toolbar
- list/pagination
- row UI
- submit progress banner

## Migration plan (low-risk)

### Phase 1 — Settings shell + parsers
1. Add `SettingsTabShell` and migrate one tab first (suggest: `SettingsZwavejsTab`).
2. Add shared numeric parsing helpers; replace duplicates in:
   - `SettingsMqttTab`, `SettingsZwavejsTab`, `SettingsFrigateTab`
   - `SetupMqttPage`, `SetupZwavejsPage`
3. Add `useDraftFromQuery`; migrate tabs incrementally.

Exit criteria:
- noticeable reduction in repeated code; tabs become primarily declarative JSX + mutation wiring.

Status: done.

### Phase 2 — Integration status UI
1. Introduce `features/integrations/components/*`.
2. Migrate settings tabs and setup pages to shared status components.

Exit criteria:
- consistent language + UI for “connected/configured/reachable” states.

Status: partially done (MQTT/Z-Wave extracted; HA/Frigate/Zigbee2MQTT still candidates).

### Phase 3 — Codes + Door Codes
1. Extract shared date and days-of-week utilities.
2. Add shared picker components; migrate both pages.

Exit criteria:
- remove duplicated helpers from `CodesPage` and `DoorCodesPage`.

Status: mostly done (datetime/days/time-window components + validation helpers + lock picker).

### Phase 4 — Import sensors
1. Extract `EntityImportRow` first.
2. Extract toolbar/list after.

Exit criteria:
- page becomes orchestration + data transforms, with rendering delegated.

Status: done (page delegates to `useImportSensorsModel` + feature components).

### Phase 5 — Rules (last)
1. Extract pure utils/types first.
2. Extract row components next.
3. Extract `RuleEditor` container and reduce `RulesPage` to composition.

Exit criteria:
- `RulesPage.tsx` no longer owns most builder logic/UI.

Status: done (rule list/editor/builder pieces moved under `features/rules/`).

## Open questions / decisions

- Do we move settings tab implementations into `features/settings/*` and keep thin wrappers in `pages/settings/*`, or keep the files where they are and only extract shared building blocks?
- Standardize parsing helpers on throws vs `{ ok, error }` results?
- How far do we go on abstractions: “shell + small shared pieces” vs a higher-level “integration settings form” framework?

# Frontend test coverage TODO

Auto-generated list of frontend source files that currently do **not** have a sibling `*.test.ts(x)` file.

- Total source files scanned: **293**
- Missing test files: **224**

## pages (7)

- `src/pages/settings/SettingsAlarmTab.tsx`
- `src/pages/settings/SettingsFrigateTab.tsx`
- `src/pages/settings/SettingsHomeAssistantTab.tsx`
- `src/pages/settings/SettingsMqttTab.tsx`
- `src/pages/settings/SettingsNotificationsTab.tsx`
- `src/pages/settings/SettingsZigbee2mqttTab.tsx`
- `src/pages/settings/SettingsZwavejsTab.tsx`

## features (105)

- `src/features/alarmSettings/components/AlarmArmModesCard.tsx`
- `src/features/alarmSettings/components/AlarmBehaviorCard.tsx`
- `src/features/alarmSettings/components/AlarmTimingCard.tsx`
- `src/features/alarmSettings/components/SystemSettingsCard.tsx`
- `src/features/codes/components/ActiveWindowPicker.tsx`
- `src/features/codes/components/AllowedArmStatesPicker.tsx`
- `src/features/codes/components/CodeCreateCard.tsx`
- `src/features/codes/components/CodeEditPanel.tsx`
- `src/features/codes/components/CodeTemporaryRestrictionsFields.tsx`
- `src/features/codes/components/DaysOfWeekPicker.tsx`
- `src/features/codes/components/ReauthPasswordField.tsx`
- `src/features/codes/components/TimeWindowFields.tsx`
- `src/features/codes/hooks/useCodeCreateModel.ts`
- `src/features/codes/utils/datetimeLocal.ts`
- `src/features/codes/utils/validation.ts`
- `src/features/doorCodes/components/DoorCodeActiveToggle.tsx`
- `src/features/doorCodes/components/DoorCodeCard.tsx`
- `src/features/doorCodes/components/DoorCodeCreateActions.tsx`
- `src/features/doorCodes/components/DoorCodeCreateBasicsFields.tsx`
- `src/features/doorCodes/components/DoorCodeCreateCard.tsx`
- `src/features/doorCodes/components/DoorCodeCreateForm.tsx`
- `src/features/doorCodes/components/DoorCodeEditActions.tsx`
- `src/features/doorCodes/components/DoorCodeEditBasicsFields.tsx`
- `src/features/doorCodes/components/DoorCodeEditContainer.tsx`
- `src/features/doorCodes/components/DoorCodeEditPanel.tsx`
- `src/features/doorCodes/components/DoorCodeLocksField.tsx`
- `src/features/doorCodes/components/DoorCodeLocksPicker.tsx`
- `src/features/doorCodes/components/DoorCodeLocksSection.tsx`
- `src/features/doorCodes/components/DoorCodeTemporaryRestrictionsFields.tsx`
- `src/features/doorCodes/components/LockEntityPicker.tsx`
- `src/features/doorCodes/utils/maxUses.ts`
- `src/features/events/components/EventRow.tsx`
- `src/features/events/constants/eventPresentation.ts`
- `src/features/events/hooks/useEventsPageModel.ts`
- `src/features/events/utils/eventMetadata.ts`
- `src/features/frigate/components/FrigateDetectionDetailDialog.tsx`
- `src/features/frigate/components/FrigateOverviewCard.tsx`
- `src/features/frigate/components/FrigateRecentDetectionsCard.tsx`
- `src/features/frigate/components/FrigateSettingsCard.tsx`
- `src/features/homeAssistant/components/HomeAssistantConnectionCard.tsx`
- `src/features/homeAssistant/components/HomeAssistantMqttAlarmEntityCard.tsx`
- `src/features/homeAssistant/components/HomeAssistantOverviewCard.tsx`
- `src/features/integrations/components/BooleanStatusPill.tsx`
- `src/features/integrations/components/ConnectionStatus.tsx`
- `src/features/integrations/components/IntegrationConnectionCard.tsx`
- `src/features/integrations/components/IntegrationOverviewCard.tsx`
- `src/features/mqtt/components/MqttSettingsCard.tsx`
- `src/features/mqtt/components/MqttSettingsForm.tsx`
- `src/features/notifications/components/PushbulletNotificationOptions.tsx`
- `src/features/rules/builder.ts`
- `src/features/rules/components/RuleEditorCard.tsx`
- `src/features/rules/components/RuleEditorContent.tsx`
- `src/features/rules/components/ThenBuilderCard.tsx`
- `src/features/rules/components/WhenBuilderCard.tsx`
- `src/features/rules/components/editor/RuleCooldownAndEntitiesFields.tsx`
- `src/features/rules/components/editor/RuleDefinitionEditor.tsx`
- `src/features/rules/components/editor/RuleEditorActions.tsx`
- `src/features/rules/components/editor/RuleMetaFields.tsx`
- `src/features/rules/components/then/AlarmArmActionFields.tsx`
- `src/features/rules/components/then/HaCallServiceActionFields.tsx`
- `src/features/rules/components/then/HaTargetEntityIdsPicker.tsx`
- `src/features/rules/components/then/ThenActionRow.tsx`
- `src/features/rules/components/then/Zigbee2mqttLightActionFields.tsx`
- `src/features/rules/components/then/Zigbee2mqttSetValueActionFields.tsx`
- `src/features/rules/components/then/Zigbee2mqttSwitchActionFields.tsx`
- `src/features/rules/components/then/ZwavejsSetValueActionFields.tsx`
- `src/features/rules/components/when/AlarmStateInConditionFields.tsx`
- `src/features/rules/components/when/EntityStateConditionFields.tsx`
- `src/features/rules/components/when/FrigatePersonDetectedConditionFields.tsx`
- `src/features/rules/components/when/FrigateStringListPicker.tsx`
- `src/features/rules/components/when/WhenConditionRow.tsx`
- `src/features/rules/queryBuilder/ActionsEditor.tsx`
- `src/features/rules/queryBuilder/RuleBuilderV2.tsx`
- `src/features/rules/queryBuilder/RuleQueryBuilder.tsx`
- `src/features/rules/queryBuilder/RulesBuilderPageActions.tsx`
- `src/features/rules/queryBuilder/converters.ts`
- `src/features/rules/queryBuilder/types.ts`
- `src/features/rules/queryBuilder/valueEditors/AlarmStateValueEditor.tsx`
- `src/features/rules/queryBuilder/valueEditors/EntityStateValueEditor.tsx`
- `src/features/rules/queryBuilder/valueEditors/FrigateValueEditor.tsx`
- `src/features/rules/utils/hydrateBuilderFromRule.ts`
- `src/features/rulesTest/components/DeltaChangeControls.tsx`
- `src/features/rulesTest/components/RulesTestHeaderActions.tsx`
- `src/features/rulesTest/components/RulesTestModeToggle.tsx`
- `src/features/rulesTest/components/RulesTestResults.tsx`
- `src/features/rulesTest/components/SavedScenariosCard.tsx`
- `src/features/rulesTest/components/ScenarioRowsEditor.tsx`
- `src/features/rulesTest/components/SimulationOptionsBar.tsx`
- `src/features/rulesTest/components/results/RulesTestChangesCard.tsx`
- `src/features/rulesTest/components/results/RulesTestResultsToolbar.tsx`
- `src/features/rulesTest/components/results/RulesTestRulesList.tsx`
- `src/features/rulesTest/utils/computeSimulationDiff.ts`
- `src/features/settings/components/AdminActionRequiredAlert.tsx`
- `src/features/settings/components/SettingsTabShell.tsx`
- `src/features/setupMqtt/components/SetupMqttCard.tsx`
- `src/features/setupMqtt/hooks/useSetupMqttModel.ts`
- `src/features/setupWizard/components/SetupWizardCard.tsx`
- `src/features/setupZwavejs/components/SetupZwavejsCard.tsx`
- `src/features/setupZwavejs/hooks/useSetupZwavejsModel.ts`
- `src/features/zigbee2mqtt/components/Zigbee2mqttActionsBar.tsx`
- `src/features/zigbee2mqtt/components/Zigbee2mqttEnableSection.tsx`
- `src/features/zigbee2mqtt/components/Zigbee2mqttRulesAndPanelSection.tsx`
- `src/features/zigbee2mqtt/components/Zigbee2mqttSettingsCard.tsx`
- `src/features/zigbee2mqtt/components/Zigbee2mqttStatusPills.tsx`
- `src/features/zwavejs/components/ZwavejsSettingsCard.tsx`

## components/alarm (6)

- `src/components/alarm/AlarmHistory.tsx`
- `src/components/alarm/AlarmPanel.tsx`
- `src/components/alarm/AlarmPanelContainer.tsx`
- `src/components/alarm/AlarmPanelView.tsx`
- `src/components/alarm/Keypad.tsx`
- `src/components/alarm/QuickActions.tsx`

## components/layout (7)

- `src/components/layout/AppShell.tsx`
- `src/components/layout/Header.tsx`
- `src/components/layout/MobileNav.tsx`
- `src/components/layout/Page.tsx`
- `src/components/layout/ProtectedRoute.tsx`
- `src/components/layout/Sidebar.tsx`
- `src/components/layout/navItems.ts`

## components/providers (4)

- `src/components/providers/AlarmRealtimeProvider.tsx`
- `src/components/providers/AppErrorBoundary.tsx`
- `src/components/providers/LayoutBootstrap.tsx`
- `src/components/providers/ThemeProvider.tsx`

## components/modals (3)

- `src/components/modals/CodeEntryModal.tsx`
- `src/components/modals/ConfirmDeleteModal.tsx`
- `src/components/modals/ModalProvider.tsx`

## components/ui (29)

- `src/components/ui/ConnectionStatusBanner.tsx`
- `src/components/ui/alert.tsx`
- `src/components/ui/badge-variants.ts`
- `src/components/ui/badge.tsx`
- `src/components/ui/button-variants.ts`
- `src/components/ui/button.tsx`
- `src/components/ui/card.tsx`
- `src/components/ui/centered-card.tsx`
- `src/components/ui/checkbox.tsx`
- `src/components/ui/datalist-input.tsx`
- `src/components/ui/date-time-range-picker.tsx`
- `src/components/ui/date-time-range-picker/DateTimeRangePickerPopover.tsx`
- `src/components/ui/empty-state.tsx`
- `src/components/ui/form-field.tsx`
- `src/components/ui/help-tip.tsx`
- `src/components/ui/icon-button.tsx`
- `src/components/ui/input.tsx`
- `src/components/ui/load-more.tsx`
- `src/components/ui/loading-inline.tsx`
- `src/components/ui/modal.tsx`
- `src/components/ui/page-header.tsx`
- `src/components/ui/pill.tsx`
- `src/components/ui/placeholder-card.tsx`
- `src/components/ui/section-card.tsx`
- `src/components/ui/select.tsx`
- `src/components/ui/spinner.tsx`
- `src/components/ui/switch.tsx`
- `src/components/ui/textarea.tsx`
- `src/components/ui/tooltip.tsx`

## hooks (21)

- `src/hooks/useAlarm.ts`
- `src/hooks/useAlarmQueries.ts`
- `src/hooks/useAlarmState.ts`
- `src/hooks/useAlarmValidation.ts`
- `src/hooks/useAuth.ts`
- `src/hooks/useCodesQueries.ts`
- `src/hooks/useCountdown.ts`
- `src/hooks/useDoorCodesQueries.ts`
- `src/hooks/useErrorBoundary.ts`
- `src/hooks/useEventsQueries.ts`
- `src/hooks/useFormErrors.ts`
- `src/hooks/useFrigate.ts`
- `src/hooks/useHomeAssistant.ts`
- `src/hooks/useHomeAssistantMqttAlarmEntity.ts`
- `src/hooks/useMqtt.ts`
- `src/hooks/useMutationErrorHandler.ts`
- `src/hooks/useQueryErrorHandler.ts`
- `src/hooks/useRulesQueries.ts`
- `src/hooks/useSettingsQueries.ts`
- `src/hooks/useZigbee2mqtt.ts`
- `src/hooks/useZwavejs.ts`

## services (19)

- `src/services/alarm.ts`
- `src/services/auth.ts`
- `src/services/codes.ts`
- `src/services/controlPanels.ts`
- `src/services/doorCodes.ts`
- `src/services/endpoints.ts`
- `src/services/entities.ts`
- `src/services/frigate.ts`
- `src/services/homeAssistant.ts`
- `src/services/integrations.ts`
- `src/services/mqtt.ts`
- `src/services/notifications.ts`
- `src/services/onboarding.ts`
- `src/services/rules.ts`
- `src/services/sensors.ts`
- `src/services/systemConfig.ts`
- `src/services/users.ts`
- `src/services/zigbee2mqtt.ts`
- `src/services/zwavejs.ts`

## lib (6)

- `src/lib/constants.ts`
- `src/lib/errorHandler.ts`
- `src/lib/notices.ts`
- `src/lib/numberParsers.ts`
- `src/lib/utils.ts`
- `src/lib/validation.ts`

## types (16)

- `src/types/alarm.ts`
- `src/types/api.ts`
- `src/types/apiEnvelope.ts`
- `src/types/code.ts`
- `src/types/controlPanels.ts`
- `src/types/doorCode.ts`
- `src/types/frigate.ts`
- `src/types/integrations.ts`
- `src/types/mqtt.ts`
- `src/types/notifications.ts`
- `src/types/ruleDefinition.ts`
- `src/types/rules.ts`
- `src/types/settings.ts`
- `src/types/user.ts`
- `src/types/zigbee2mqtt.ts`
- `src/types/zwavejs.ts`

## other (1)

- `src/App.tsx`

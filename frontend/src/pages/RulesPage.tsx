import { Page } from '@/components/layout'
import { RulesListCard } from '@/features/rules/components/RulesListCard'
import { RuleEditorCard } from '@/features/rules/components/RuleEditorCard'
import { RulesPageActions } from '@/features/rules/components/RulesPageActions'
import { RulesPageNotices } from '@/features/rules/components/RulesPageNotices'
import { useRulesPageModel } from '@/features/rules/hooks/useRulesPageModel'

export function RulesPage() {
  const model = useRulesPageModel()

  return (
    <Page
      title="Rules"
      description="Create trigger/disarm/arm rules (builder MVP)."
      actions={
        <RulesPageActions
          isSaving={model.isSaving}
          onSyncEntities={() => void model.onSyncEntities()}
          onSyncZwavejsEntities={() => void model.onSyncZwavejsEntities()}
          onRunRules={() => void model.onRunRules()}
          onRefresh={model.onRefresh}
        />
      }
    >
      <RulesPageNotices notice={model.notice} error={model.displayedError} />

      <RuleEditorCard
        editingId={model.editingId}
        isSaving={model.isSaving}
        ruleKinds={model.ruleKinds}
        name={model.name}
        setName={model.setName}
        kind={model.kind}
        setKind={model.setKind}
        enabled={model.enabled}
        setEnabled={model.setEnabled}
        priority={model.priority}
        setPriority={model.setPriority}
        advanced={model.advanced}
        setAdvanced={model.setAdvanced}
        cooldownSeconds={model.cooldownSeconds}
        setCooldownSeconds={model.setCooldownSeconds}
        entityIdsText={model.entityIdsText}
        setEntityIdsText={model.setEntityIdsText}
        derivedEntityIds={model.derivedEntityIds}
        derivedEntityIdsText={model.derivedEntityIdsText}
        builderDefinitionText={model.builderDefinitionText}
        definitionText={model.definitionText}
        setDefinitionText={model.setDefinitionText}
        entitiesLength={model.entitiesLength}
        whenOperator={model.whenOperator}
        setWhenOperator={model.setWhenOperator}
        forSecondsText={model.forSecondsText}
        setForSecondsText={model.setForSecondsText}
        entitySourceFilter={model.entitySourceFilter}
        setEntitySourceFilter={model.setEntitySourceFilter}
        conditions={model.conditions}
        setConditions={model.setConditions}
        alarmStatePickerByConditionId={model.alarmStatePickerByConditionId}
        setAlarmStatePickerByConditionId={model.setAlarmStatePickerByConditionId}
        frigateCameraPickerByConditionId={model.frigateCameraPickerByConditionId}
        setFrigateCameraPickerByConditionId={model.setFrigateCameraPickerByConditionId}
        frigateZonePickerByConditionId={model.frigateZonePickerByConditionId}
        setFrigateZonePickerByConditionId={model.setFrigateZonePickerByConditionId}
        actions={model.actions}
        setActions={model.setActions}
        targetEntityPickerByActionId={model.targetEntityPickerByActionId}
        setTargetEntityPickerByActionId={model.setTargetEntityPickerByActionId}
        updateHaActionTargetEntityIds={model.updateHaActionTargetEntityIds}
        entityIdOptions={model.entityIdOptions}
        entityIdSet={model.entityIdSet}
        frigateOptions={model.frigateOptions}
        onSubmit={model.onSubmit}
        onCancel={model.onCancel}
        onDelete={model.onDelete}
      />

      <RulesListCard isLoading={model.isLoading} rules={model.rules} onEdit={model.onStartEdit} />
    </Page>
  )
}

export default RulesPage

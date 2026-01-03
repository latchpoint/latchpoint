import type { Dispatch, SetStateAction } from 'react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

import type { RuleKind } from '@/types'
import { WhenBuilderCard } from '@/features/rules/components/WhenBuilderCard'
import { ThenBuilderCard } from '@/features/rules/components/ThenBuilderCard'
import type { ActionRow, ConditionRow, WhenOperator } from '@/features/rules/builder'
import { RuleCooldownAndEntitiesFields } from '@/features/rules/components/editor/RuleCooldownAndEntitiesFields'
import { RuleDefinitionEditor } from '@/features/rules/components/editor/RuleDefinitionEditor'
import { RuleEditorActions } from '@/features/rules/components/editor/RuleEditorActions'
import { RuleMetaFields } from '@/features/rules/components/editor/RuleMetaFields'

type EntitySourceFilter = 'all' | 'home_assistant' | 'zwavejs' | 'zigbee2mqtt'

type FrigateOptions = {
  isLoading: boolean
  hasError: boolean
  knownCameras: string[]
  zonesByCamera: Record<string, string[]>
}

export type RuleEditorContentProps = {
  editingId: number | null
  isSaving: boolean

  ruleKinds: { value: RuleKind; label: string }[]

  name: string
  setName: (next: string) => void
  kind: RuleKind
  setKind: (next: RuleKind) => void
  enabled: boolean
  setEnabled: (next: boolean) => void
  priority: number
  setPriority: (next: number) => void

  advanced: boolean
  setAdvanced: Dispatch<SetStateAction<boolean>>

  cooldownSeconds: string
  setCooldownSeconds: (next: string) => void

  entityIdsText: string
  setEntityIdsText: (next: string) => void
  derivedEntityIds: string[]
  derivedEntityIdsText: string
  builderDefinitionText: string
  definitionText: string
  setDefinitionText: (next: string) => void

  entitiesLength: number

  whenOperator: WhenOperator
  setWhenOperator: (next: WhenOperator) => void
  forSecondsText: string
  setForSecondsText: (next: string) => void
  entitySourceFilter: EntitySourceFilter
  setEntitySourceFilter: (next: EntitySourceFilter) => void
  conditions: ConditionRow[]
  setConditions: Dispatch<SetStateAction<ConditionRow[]>>
  alarmStatePickerByConditionId: Record<string, string>
  setAlarmStatePickerByConditionId: Dispatch<SetStateAction<Record<string, string>>>
  frigateCameraPickerByConditionId: Record<string, string>
  setFrigateCameraPickerByConditionId: Dispatch<SetStateAction<Record<string, string>>>
  frigateZonePickerByConditionId: Record<string, string>
  setFrigateZonePickerByConditionId: Dispatch<SetStateAction<Record<string, string>>>

  actions: ActionRow[]
  setActions: Dispatch<SetStateAction<ActionRow[]>>
  targetEntityPickerByActionId: Record<string, string>
  setTargetEntityPickerByActionId: Dispatch<SetStateAction<Record<string, string>>>
  updateHaActionTargetEntityIds: (actionId: string, nextEntityIds: string[]) => void

  entityIdOptions: string[]
  entityIdSet: Set<string>
  frigateOptions: FrigateOptions

  onSubmit: () => void
  onCancel: () => void
  onDelete: () => void
}

export function RuleEditorContent({
  editingId,
  isSaving,
  ruleKinds,
  name,
  setName,
  kind,
  setKind,
  enabled,
  setEnabled,
  priority,
  setPriority,
  advanced,
  setAdvanced,
  cooldownSeconds,
  setCooldownSeconds,
  entityIdsText,
  setEntityIdsText,
  derivedEntityIds,
  derivedEntityIdsText,
  builderDefinitionText,
  definitionText,
  setDefinitionText,
  entitiesLength,
  whenOperator,
  setWhenOperator,
  forSecondsText,
  setForSecondsText,
  entitySourceFilter,
  setEntitySourceFilter,
  conditions,
  setConditions,
  alarmStatePickerByConditionId,
  setAlarmStatePickerByConditionId,
  frigateCameraPickerByConditionId,
  setFrigateCameraPickerByConditionId,
  frigateZonePickerByConditionId,
  setFrigateZonePickerByConditionId,
  actions,
  setActions,
  targetEntityPickerByActionId,
  setTargetEntityPickerByActionId,
  updateHaActionTargetEntityIds,
  entityIdOptions,
  entityIdSet,
  frigateOptions,
  onSubmit,
  onCancel,
  onDelete,
}: RuleEditorContentProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{editingId == null ? 'New Rule' : `Edit Rule #${editingId}`}</CardTitle>
        <CardDescription>Builder supports simple entity-state conditions, optional “for”, and basic actions. JSON is always stored.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <RuleMetaFields
          ruleKinds={ruleKinds}
          name={name}
          setName={setName}
          kind={kind}
          setKind={setKind}
          enabled={enabled}
          setEnabled={setEnabled}
          priority={priority}
          setPriority={setPriority}
          advanced={advanced}
          onToggleAdvanced={() =>
            setAdvanced((v) => {
              const next = !v
              if (next) {
                setDefinitionText(builderDefinitionText)
                setEntityIdsText(derivedEntityIdsText)
              }
              return next
            })
          }
        />

        <RuleCooldownAndEntitiesFields
          advanced={advanced}
          cooldownSeconds={cooldownSeconds}
          setCooldownSeconds={setCooldownSeconds}
          entitiesLength={entitiesLength}
          entityIdsText={entityIdsText}
          setEntityIdsText={setEntityIdsText}
          derivedEntityIds={derivedEntityIds}
          derivedEntityIdsText={derivedEntityIdsText}
        />

        {!advanced ? (
          <WhenBuilderCard
            whenOperator={whenOperator}
            setWhenOperator={setWhenOperator}
            forSecondsText={forSecondsText}
            setForSecondsText={setForSecondsText}
            entitySourceFilter={entitySourceFilter}
            setEntitySourceFilter={setEntitySourceFilter}
            conditions={conditions}
            setConditions={setConditions}
            isSaving={isSaving}
            entityIdOptions={entityIdOptions}
            entityIdSet={entityIdSet}
            entitiesLength={entitiesLength}
            alarmStatePickerByConditionId={alarmStatePickerByConditionId}
            setAlarmStatePickerByConditionId={setAlarmStatePickerByConditionId}
            frigateCameraPickerByConditionId={frigateCameraPickerByConditionId}
            setFrigateCameraPickerByConditionId={setFrigateCameraPickerByConditionId}
            frigateZonePickerByConditionId={frigateZonePickerByConditionId}
            setFrigateZonePickerByConditionId={setFrigateZonePickerByConditionId}
            frigateOptions={frigateOptions}
          />
        ) : null}

        {!advanced ? (
          <ThenBuilderCard
            actions={actions}
            setActions={setActions}
            isSaving={isSaving}
            entityIdOptions={entityIdOptions}
            targetEntityPickerByActionId={targetEntityPickerByActionId}
            setTargetEntityPickerByActionId={setTargetEntityPickerByActionId}
            updateHaActionTargetEntityIds={updateHaActionTargetEntityIds}
          />
        ) : null}

        <RuleDefinitionEditor advanced={advanced} builderDefinitionText={builderDefinitionText} definitionText={definitionText} setDefinitionText={setDefinitionText} />

        <RuleEditorActions editingId={editingId} isSaving={isSaving} onSubmit={onSubmit} onCancel={onCancel} onDelete={onDelete} />
      </CardContent>
    </Card>
  )
}

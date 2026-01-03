import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Entity, Rule, RuleKind } from '@/types'
import { queryKeys } from '@/types'
import { getErrorMessage } from '@/types/errors'
import { parseRuleDefinition, type RuleDefinition } from '@/types/ruleDefinition'
import {
  buildDefinitionFromBuilder,
  parseEntityIds,
  uniqueId,
  type ActionRow,
  type ConditionRow,
  type EntityStateConditionRow,
  type WhenOperator,
} from '@/features/rules/builder'
import { hydrateBuilderFromRule } from '@/features/rules/utils/hydrateBuilderFromRule'
import {
  useDeleteRuleMutation,
  useEntitiesQuery,
  useRulesQuery,
  useRunRulesMutation,
  useSaveRuleMutation,
  useSyncEntitiesMutation,
} from '@/hooks/useRulesQueries'
import { useSyncZwavejsEntitiesMutation } from '@/hooks/useZwavejs'
import { useFrigateOptionsQuery } from '@/hooks/useFrigate'

const ruleKinds: { value: RuleKind; label: string }[] = [
  { value: 'trigger', label: 'Trigger' },
  { value: 'disarm', label: 'Disarm' },
  { value: 'arm', label: 'Arm' },
  { value: 'suppress', label: 'Suppress' },
  { value: 'escalate', label: 'Escalate' },
]

export function useRulesPageModel() {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const frigateOptionsQuery = useFrigateOptionsQuery()

  const rulesQuery = useRulesQuery()
  const entitiesQuery = useEntitiesQuery()

  const rules: Rule[] = useMemo(() => rulesQuery.data ?? [], [rulesQuery.data])
  const entities: Entity[] = useMemo(() => entitiesQuery.data ?? [], [entitiesQuery.data])
  const isLoading = rulesQuery.isLoading || entitiesQuery.isLoading

  const [entitySourceFilter, setEntitySourceFilter] = useState<'all' | 'home_assistant' | 'zwavejs' | 'zigbee2mqtt'>('all')
  const filteredEntities = useMemo(() => {
    if (entitySourceFilter === 'all') return entities
    return entities.filter((e) => e.source === entitySourceFilter)
  }, [entities, entitySourceFilter])

  const [editingId, setEditingId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [kind, setKind] = useState<RuleKind>('trigger')
  const [enabled, setEnabled] = useState(true)
  const [priority, setPriority] = useState(0)
  const [cooldownSeconds, setCooldownSeconds] = useState<string>('')

  const [advanced, setAdvanced] = useState(false)
  const [definitionText, setDefinitionText] = useState('{\n  "when": {},\n  "then": []\n}')
  const [entityIdsText, setEntityIdsText] = useState('')

  const [whenOperator, setWhenOperator] = useState<WhenOperator>('all')
  const [forSecondsText, setForSecondsText] = useState<string>('')
  const [conditions, setConditions] = useState<ConditionRow[]>([
    { id: uniqueId(), type: 'entity_state', entityId: '', equals: 'on', negate: false },
  ])
  const [actions, setActions] = useState<ActionRow[]>([{ id: uniqueId(), type: 'alarm_trigger' }])
  const [targetEntityPickerByActionId, setTargetEntityPickerByActionId] = useState<Record<string, string>>({})
  const [frigateCameraPickerByConditionId, setFrigateCameraPickerByConditionId] = useState<Record<string, string>>({})
  const [frigateZonePickerByConditionId, setFrigateZonePickerByConditionId] = useState<Record<string, string>>({})
  const [alarmStatePickerByConditionId, setAlarmStatePickerByConditionId] = useState<Record<string, string>>({})

  const entityIdOptions = useMemo(() => filteredEntities.map((e) => e.entityId), [filteredEntities])
  const entityIdSet = useMemo(() => new Set(filteredEntities.map((e) => e.entityId)), [filteredEntities])

  const derivedEntityIds = useMemo(() => {
    const fromConditions = conditions
      .filter((c): c is EntityStateConditionRow => c.type === 'entity_state')
      .map((c) => c.entityId.trim())
      .filter(Boolean)
    return Array.from(new Set(fromConditions)).sort()
  }, [conditions])

  const resetForm = () => {
    setEditingId(null)
    setName('')
    setKind('trigger')
    setEnabled(true)
    setPriority(0)
    setCooldownSeconds('')

    setAdvanced(false)
    setWhenOperator('all')
    setForSecondsText('')
    setConditions([{ id: uniqueId(), type: 'entity_state', entityId: '', equals: 'on', negate: false }])
    setActions([{ id: uniqueId(), type: 'alarm_trigger' }])
    setEntityIdsText('')
    setDefinitionText('{\n  "when": {},\n  "then": []\n}')
  }

  const syncEntitiesMutation = useSyncEntitiesMutation()
  const syncZwavejsEntitiesMutation = useSyncZwavejsEntitiesMutation()
  const runRulesMutation = useRunRulesMutation()
  const saveRuleMutation = useSaveRuleMutation()
  const deleteRuleMutation = useDeleteRuleMutation()

  const isSaving =
    syncEntitiesMutation.isPending ||
    syncZwavejsEntitiesMutation.isPending ||
    runRulesMutation.isPending ||
    saveRuleMutation.isPending ||
    deleteRuleMutation.isPending

  const syncEntities = async () => {
    setNotice(null)
    setError(null)
    try {
      const result = await syncEntitiesMutation.mutateAsync()
      setNotice(result.notice)
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to sync entities')
    }
  }

  const syncZwavejsEntities = async () => {
    setNotice(null)
    setError(null)
    try {
      const result = await syncZwavejsEntitiesMutation.mutateAsync()
      setNotice(result.notice)
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to sync Z-Wave JS entities')
    }
  }

  const runRulesNow = async () => {
    setNotice(null)
    setError(null)
    try {
      const result = await runRulesMutation.mutateAsync()
      setNotice(result.notice)
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to run rules')
    }
  }

  const builderSeconds = useMemo(() => {
    const parsed = forSecondsText.trim() === '' ? null : Number.parseInt(forSecondsText.trim(), 10)
    if (typeof parsed === 'number' && Number.isNaN(parsed)) return null
    return parsed
  }, [forSecondsText])

  const builderDefinitionText = useMemo(() => {
    const def = buildDefinitionFromBuilder(whenOperator, conditions, builderSeconds, actions)
    return JSON.stringify(def, null, 2)
  }, [whenOperator, conditions, builderSeconds, actions])

  const frigateOptions = useMemo(
    () => ({
      isLoading: frigateOptionsQuery.isLoading,
      hasError: Boolean(frigateOptionsQuery.error),
      knownCameras: frigateOptionsQuery.data?.cameras ?? [],
      zonesByCamera: frigateOptionsQuery.data?.zonesByCamera ?? {},
    }),
    [frigateOptionsQuery.data, frigateOptionsQuery.error, frigateOptionsQuery.isLoading]
  )

  const derivedEntityIdsText = useMemo(() => derivedEntityIds.join('\n'), [derivedEntityIds])

  const updateHaActionTargetEntityIds = (actionId: string, nextEntityIds: string[]) => {
    const normalized = Array.from(new Set(nextEntityIds.map((id) => id.trim()).filter(Boolean)))
    setActions((prev) =>
      prev.map((row) => {
        if (row.id !== actionId) return row
        if (row.type !== 'ha_call_service') return row
        return { ...row, targetEntityIds: normalized.join(', ') }
      }) as ActionRow[]
    )
  }

  const displayedError = error || getErrorMessage(rulesQuery.error) || getErrorMessage(entitiesQuery.error) || null

  const startEdit = (rule: Rule) => {
    setEditingId(rule.id)
    setName(rule.name)
    setKind(rule.kind)
    setEnabled(rule.enabled)
    setPriority(rule.priority)
    setCooldownSeconds(rule.cooldownSeconds == null ? '' : String(rule.cooldownSeconds))
    setNotice(null)
    setError(null)

    setDefinitionText(JSON.stringify(rule.definition ?? {}, null, 2))
    setEntityIdsText(rule.entityIds.join('\n'))

    const hydrated = hydrateBuilderFromRule(rule)
    if (!hydrated) return
    setWhenOperator(hydrated.whenOperator)
    setForSecondsText(hydrated.forSecondsText)
    setConditions(hydrated.conditions)
    setActions(hydrated.actions)
  }

  const submit = async () => {
    setError(null)
    setNotice(null)
    try {
      const trimmedName = name.trim()
      if (!trimmedName) {
        setError('Rule name is required.')
        return
      }

      let parsedDefinition: RuleDefinition
      try {
        const parsed = JSON.parse(advanced ? definitionText : builderDefinitionText)
        const validated = parseRuleDefinition(parsed)
        if (!validated) {
          setError('Definition must be a valid rule structure with "when" and "then" properties.')
          return
        }
        parsedDefinition = validated
      } catch {
        setError('Definition is not valid JSON.')
        return
      }

      const cooldown = cooldownSeconds.trim() === '' ? null : Number.parseInt(cooldownSeconds.trim(), 10)
      if (cooldownSeconds.trim() !== '' && Number.isNaN(cooldown)) {
        setError('Cooldown seconds must be a number.')
        return
      }

      const entityIds = advanced ? parseEntityIds(entityIdsText) : derivedEntityIds
      const payload = {
        name: trimmedName,
        kind,
        enabled,
        priority,
        schemaVersion: 1,
        definition: parsedDefinition,
        cooldownSeconds: cooldown,
        entityIds,
      }

      const result = await saveRuleMutation.mutateAsync({ id: editingId, payload })
      setNotice(result.notice)
      resetForm()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save rule')
    }
  }

  const remove = async () => {
    if (editingId == null) return
    setError(null)
    setNotice(null)
    try {
      const result = await deleteRuleMutation.mutateAsync(editingId)
      setNotice(result.notice)
      resetForm()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to delete rule')
    }
  }

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.rules.all })
    void queryClient.invalidateQueries({ queryKey: queryKeys.entities.all })
  }

  return {
    ruleKinds,
    rules,
    entities,
    isLoading,
    isSaving,
    displayedError,
    notice,
    editingId,
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
    entitiesLength: entities.length,
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
    onSyncEntities: syncEntities,
    onSyncZwavejsEntities: syncZwavejsEntities,
    onRunRules: runRulesNow,
    onRefresh: refresh,
    onStartEdit: startEdit,
    onSubmit: submit,
    onCancel: resetForm,
    onDelete: remove,
  }
}

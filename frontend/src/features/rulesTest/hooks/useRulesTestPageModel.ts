import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { rulesService } from '@/services'
import type { Entity, RuleSimulateResult } from '@/types'
import { queryKeys } from '@/types'
import { getErrorMessage } from '@/lib/errors'
import { useEntitiesQuery, useSyncEntitiesMutation } from '@/hooks/useRulesQueries'
import { useSyncZwavejsEntitiesMutation } from '@/hooks/useZwavejs'
import {
  createScenarioRow,
  loadSavedScenarios,
  saveSavedScenarios,
  type SavedScenario,
  type ScenarioRow,
} from '@/features/rulesTest/scenarios'
import type { RulesTestMode } from '@/features/rulesTest/components/RulesTestModeToggle'

type Row = ScenarioRow

type SimulationResult = RuleSimulateResult

export function useRulesTestPageModel() {
  const queryClient = useQueryClient()

  const entitiesQuery = useEntitiesQuery()
  const entities: Entity[] = useMemo(() => entitiesQuery.data ?? [], [entitiesQuery.data])

  const [rows, setRows] = useState<Row[]>([createScenarioRow()])
  const [mode, setMode] = useState<RulesTestMode>('scenario')
  const [deltaEntityId, setDeltaEntityId] = useState('')
  const [deltaState, setDeltaState] = useState('on')
  const [assumeForSeconds, setAssumeForSeconds] = useState<string>('')
  const [alarmState, setAlarmState] = useState<string>('')
  const [isRunning, setIsRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [baselineResult, setBaselineResult] = useState<SimulationResult | null>(null)
  const [scenarioName, setScenarioName] = useState('')
  const [savedScenarios, setSavedScenarios] = useState<SavedScenario[]>([])
  const [selectedScenario, setSelectedScenario] = useState<string>('')

  const entityIdOptions = useMemo(() => entities.map((e) => e.entityId), [entities])
  const entitiesById = useMemo(() => {
    const map = new Map<string, Entity>()
    for (const e of entities) map.set(e.entityId, e)
    return map
  }, [entities])

  useEffect(() => {
    setSavedScenarios(loadSavedScenarios())
  }, [])

  const syncEntitiesMutation = useSyncEntitiesMutation()
  const syncZwavejsEntitiesMutation = useSyncZwavejsEntitiesMutation()

  const syncEntities = async () => {
    setError(null)
    try {
      await syncEntitiesMutation.mutateAsync()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to sync entities')
    }
  }

  const syncZwavejsEntities = async () => {
    setError(null)
    try {
      await syncZwavejsEntitiesMutation.mutateAsync()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to sync Z-Wave JS entities')
    }
  }

  const isLoading =
    entitiesQuery.isLoading ||
    entitiesQuery.isFetching ||
    syncEntitiesMutation.isPending ||
    syncZwavejsEntitiesMutation.isPending
  const displayedError = error || getErrorMessage(entitiesQuery.error) || null

  const entityStates = useMemo(() => {
    const out: Record<string, string> = {}
    for (const row of rows) {
      const entityId = row.entityId.trim()
      const state = row.state.trim()
      if (!entityId || !state) continue
      out[entityId] = state
    }
    return out
  }, [rows])

  const deltaEntityStates = useMemo(() => {
    const entityId = deltaEntityId.trim()
    const state = deltaState.trim()
    if (!entityId || !state) return {}
    return { [entityId]: state }
  }, [deltaEntityId, deltaState])

  const setRowEntityId = (rowId: string, nextEntityId: string) => {
    setRows((prev) =>
      prev.map((r) => {
        if (r.id !== rowId) return r
        const entity = entitiesById.get(nextEntityId.trim())
        const baseline = entity?.lastState ?? ''
        const shouldAutofill = r.entityId.trim() !== nextEntityId.trim() && (r.state.trim() === '' || r.state === 'on')
        return {
          ...r,
          entityId: nextEntityId,
          state: shouldAutofill && baseline ? baseline : r.state,
        }
      })
    )
  }

  const parseAssumeForSeconds = (): { ok: true; value: number | undefined } | { ok: false; error: string } => {
    const trimmed = assumeForSeconds.trim()
    if (trimmed === '') return { ok: true, value: undefined }
    const assume = Number.parseInt(trimmed, 10)
    if (assume == null || Number.isNaN(assume)) return { ok: false, error: 'Assume-for seconds must be a number.' }
    return { ok: true, value: assume }
  }

  const simulate = async () => {
    setIsRunning(true)
    setError(null)
    setResult(null)
    try {
      const assume = parseAssumeForSeconds()
      if (!assume.ok) {
        setError(assume.error)
        return
      }
      const res = await rulesService.simulate({
        entityStates,
        assumeForSeconds: assume.value,
        alarmState: alarmState.trim() || undefined,
      })
      setResult(res as SimulationResult)
    } catch (err) {
      setError(getErrorMessage(err) || 'Simulation failed')
    } finally {
      setIsRunning(false)
    }
  }

  const simulateDelta = async () => {
    setIsRunning(true)
    setError(null)
    setResult(null)
    setBaselineResult(null)
    try {
      const assume = parseAssumeForSeconds()
      if (!assume.ok) {
        setError(assume.error)
        return
      }
      const base = await rulesService.simulate({
        entityStates: {},
        assumeForSeconds: assume.value,
        alarmState: alarmState.trim() || undefined,
      })
      const changed = await rulesService.simulate({
        entityStates: deltaEntityStates,
        assumeForSeconds: assume.value,
        alarmState: alarmState.trim() || undefined,
      })
      setBaselineResult(base as SimulationResult)
      setResult(changed as SimulationResult)
    } catch (err) {
      setError(getErrorMessage(err) || 'Simulation failed')
    } finally {
      setIsRunning(false)
    }
  }

  const saveScenario = () => {
    const trimmed = scenarioName.trim()
    if (!trimmed) {
      setError('Scenario name is required to save.')
      return
    }
    const next: SavedScenario = { name: trimmed, rows, assumeForSeconds }
    const updated = [next, ...savedScenarios.filter((s) => s.name !== trimmed)].slice(0, 20)
    setSavedScenarios(updated)
    saveSavedScenarios(updated)
    setSelectedScenario(trimmed)
  }

  const loadScenario = (nameToLoad: string) => {
    const found = savedScenarios.find((s) => s.name === nameToLoad)
    if (!found) return
    setRows(found.rows.length ? found.rows : [createScenarioRow()])
    setAssumeForSeconds(found.assumeForSeconds || '')
    setSelectedScenario(found.name)
    setResult(null)
    setError(null)
  }

  const deleteScenario = () => {
    if (!selectedScenario) return
    const updated = savedScenarios.filter((s) => s.name !== selectedScenario)
    setSavedScenarios(updated)
    saveSavedScenarios(updated)
    setSelectedScenario('')
  }

  const refreshEntities = () => {
    setError(null)
    void queryClient.invalidateQueries({ queryKey: queryKeys.entities.all })
  }

  return {
    entitiesQuery,
    entities,
    entityIdOptions,
    entitiesById,
    rows,
    setRows,
    setRowEntityId,
    mode,
    setMode,
    deltaEntityId,
    setDeltaEntityId,
    deltaState,
    setDeltaState,
    assumeForSeconds,
    setAssumeForSeconds,
    alarmState,
    setAlarmState,
    isLoading,
    isRunning,
    displayedError,
    result,
    baselineResult,
    scenarioName,
    setScenarioName,
    savedScenarios,
    selectedScenario,
    setSelectedScenario,
    syncEntities,
    syncZwavejsEntities,
    refreshEntities,
    simulate,
    simulateDelta,
    saveScenario,
    loadScenario,
    deleteScenario,
  }
}

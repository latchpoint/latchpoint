import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { getErrorMessage } from '@/lib/errors'
import { sensorsService } from '@/services'
import type { HomeAssistantEntity } from '@/services/homeAssistant'
import { queryKeys } from '@/types'
import { useHomeAssistantEntities, useHomeAssistantStatus } from '@/hooks/useHomeAssistant'
import { useSensorsQuery } from '@/hooks/useAlarmQueries'
import type { EntityImportViewMode } from '@/features/sensors/components/EntityImportToolbar'

type SubmitProgress = { current: number; total: number }
type ImportSuccess = { count: number; names: string[] }

export function useImportSensorsModel() {
  const queryClient = useQueryClient()
  const haStatusQuery = useHomeAssistantStatus()
  const haEntitiesQuery = useHomeAssistantEntities()
  const sensorsQuery = useSensorsQuery()

  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<ImportSuccess | null>(null)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [nameOverrides, setNameOverrides] = useState<Record<string, string>>({})
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitProgress, setSubmitProgress] = useState<SubmitProgress | null>(null)
  const [viewMode, setViewMode] = useState<EntityImportViewMode>('available')
  const [visibleCount, setVisibleCount] = useState(50)

  const sensors = useMemo(() => sensorsQuery.data ?? [], [sensorsQuery.data])

  const haStatusError = useMemo(() => {
    const status = haStatusQuery.data
    if (haStatusQuery.isError) return getErrorMessage(haStatusQuery.error) || 'Failed to check Home Assistant status'
    if (!status) return null
    if (!status.configured) {
      return 'Home Assistant is not configured. Configure it in Settings → Home Assistant.'
    }
    if (!status.reachable) {
      return status.error || 'Home Assistant is offline/unreachable. Check network and token.'
    }
    return null
  }, [haStatusQuery.data, haStatusQuery.error, haStatusQuery.isError])

  const entitiesLoadError = useMemo(() => {
    if (haStatusError) return haStatusError
    if (haEntitiesQuery.isError) return getErrorMessage(haEntitiesQuery.error) || 'Failed to load entities'
    return null
  }, [haEntitiesQuery.error, haEntitiesQuery.isError, haStatusError])

  const entities = useMemo<HomeAssistantEntity[]>(() => {
    if (entitiesLoadError) return []
    return haEntitiesQuery.data ?? []
  }, [haEntitiesQuery.data, entitiesLoadError])

  const isLoading = haEntitiesQuery.isLoading || haStatusQuery.isLoading || sensorsQuery.isLoading || isSubmitting
  const bannerError = error || entitiesLoadError || null

  const allSensorEntities = useMemo(
    () => entities.filter((entity) => entity.domain === 'binary_sensor'),
    [entities],
  )

  const importedByEntityId = useMemo(() => {
    const map = new Map<string, { sensorId: number }>()
    for (const sensor of sensors) {
      if (sensor.entityId) {
        map.set(sensor.entityId, { sensorId: sensor.id })
      }
    }
    return map
  }, [sensors])

  const existingEntityIds = useMemo(() => new Set(importedByEntityId.keys()), [importedByEntityId])

  const importedSensorEntities = useMemo(
    () => allSensorEntities.filter((entity) => existingEntityIds.has(entity.entityId)),
    [allSensorEntities, existingEntityIds],
  )

  const availableSensorEntities = useMemo(
    () => allSensorEntities.filter((entity) => !existingEntityIds.has(entity.entityId)),
    [allSensorEntities, existingEntityIds],
  )

  const filtered = useMemo(() => {
    const source = viewMode === 'imported' ? importedSensorEntities : availableSensorEntities
    if (!query.trim()) return source
    const q = query.toLowerCase()
    return source.filter(
      (entity) =>
        entity.name.toLowerCase().includes(q) ||
        entity.entityId.toLowerCase().includes(q) ||
        (entity.deviceClass || '').toLowerCase().includes(q),
    )
  }, [viewMode, importedSensorEntities, availableSensorEntities, query])

  useEffect(() => {
    setVisibleCount(50)
  }, [filtered])

  const visible = useMemo(() => filtered.slice(0, visibleCount), [filtered, visibleCount])
  const canLoadMore = visibleCount < filtered.length

  const selectedEntities = useMemo(() => filtered.filter((e) => selected[e.entityId]), [filtered, selected])

  const getRowModel = (entity: HomeAssistantEntity) => {
    const alreadyImported = existingEntityIds.has(entity.entityId)
    const checked = Boolean(selected[entity.entityId])
    const imported = importedByEntityId.get(entity.entityId)
    const nameOverride = nameOverrides[entity.entityId] ?? entity.name
    return {
      alreadyImported,
      checked,
      importedSensorId: imported?.sensorId ?? null,
      nameOverride,
    }
  }

  const setEntityChecked = (entity: HomeAssistantEntity, nextChecked: boolean) => {
    setSelected((prev) => ({ ...prev, [entity.entityId]: nextChecked }))
  }

  const setEntityNameOverride = (entityId: string, next: string) => {
    setNameOverrides((prev) => ({ ...prev, [entityId]: next }))
  }

  const loadMore = () => setVisibleCount((c) => c + 50)

  const submit = async () => {
    setError(null)
    setSuccess(null)
    setIsSubmitting(true)
    setSubmitProgress({ current: 0, total: selectedEntities.length })
    const importedNames: string[] = []
    try {
      let index = 0
      for (const entity of selectedEntities) {
        index += 1
        setSubmitProgress({ current: index, total: selectedEntities.length })
        const name = (nameOverrides[entity.entityId] || entity.name || entity.entityId).trim()

        await sensorsService.createSensor({
          name,
          entityId: entity.entityId,
          isActive: true,
        })
        importedNames.push(name || entity.entityId)
      }

      await queryClient.invalidateQueries({ queryKey: queryKeys.sensors.all })
      await queryClient.invalidateQueries({ queryKey: queryKeys.alarm.state })
      setSelected({})
      setSuccess({ count: importedNames.length, names: importedNames.slice(0, 5) })
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to import sensors')
    } finally {
      setIsSubmitting(false)
      setSubmitProgress(null)
    }
  }

  return {
    query,
    setQuery,
    viewMode,
    setViewMode,
    visibleCount,
    isLoading,
    bannerError,
    success,
    visible,
    filteredCount: filtered.length,
    canLoadMore,
    loadMore,
    allCount: allSensorEntities.length,
    importedCount: importedSensorEntities.length,
    availableCount: availableSensorEntities.length,
    selectedCount: selectedEntities.length,
    isSubmitting,
    submitProgress,
    submit,
    getRowModel,
    setEntityChecked,
    setEntityNameOverride,
  }
}

import { useMemo } from 'react'
import type { Sensor } from '@/types'
import { useSensorsQuery, useAlarmSettingsQuery } from '@/hooks/useAlarmQueries'

export interface UseAlarmValidationReturn {
  // Sensors
  sensors: Sensor[]

  // Validation results
  openSensors: Sensor[]
  unknownSensors: Sensor[]

  // Derived
  canArm: boolean
  hasWarnings: boolean

  // Status
  isLoading: boolean
}

/**
 * Alarm validation hook.
 * Provides sensor validation logic for arming decisions.
 */
export function useAlarmValidation(): UseAlarmValidationReturn {
  const sensorsQuery = useSensorsQuery()
  const settingsQuery = useAlarmSettingsQuery()

  const sensors = useMemo(() => sensorsQuery.data ?? [], [sensorsQuery.data])
  const settings = settingsQuery.data ?? null

  const isLoading = sensorsQuery.isLoading || settingsQuery.isLoading

  // Helper to filter sensors used in rules
  const isUsedInRules = (sensor: Sensor) => sensor.usedInRules !== false

  // Find sensors that are open and would prevent arming
  const openSensors = useMemo(
    () =>
      sensors.filter(
        (sensor) => isUsedInRules(sensor) && sensor.currentState === 'open' && sensor.isActive
      ),
    [sensors]
  )

  // Find sensors with unknown state
  const unknownSensors = useMemo(
    () =>
      sensors.filter(
        (sensor) =>
          isUsedInRules(sensor) &&
          sensor.isActive &&
          !!sensor.entityId &&
          sensor.currentState === 'unknown'
      ),
    [sensors]
  )

  // Can arm if no open sensors OR force arm is enabled
  const canArm = openSensors.length === 0 || (settings?.sensorBehavior?.forceArmEnabled ?? false)

  // Has warnings if there are open or unknown sensors
  const hasWarnings = openSensors.length > 0 || unknownSensors.length > 0

  return {
    sensors,
    openSensors,
    unknownSensors,
    canArm,
    hasWarnings,
    isLoading,
  }
}

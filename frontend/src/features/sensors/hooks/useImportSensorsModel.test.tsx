import React, { type PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useImportSensorsModel } from '@/features/sensors/hooks/useImportSensorsModel'
import { queryKeys } from '@/types'

const createSensor = vi.fn().mockResolvedValue({ id: 1 })

vi.mock('@/services', () => {
  return {
    sensorsService: {
      createSensor: (args: any) => createSensor(args),
    },
  }
})

vi.mock('@/hooks/useHomeAssistant', () => {
  return {
    useHomeAssistantStatus: () => ({ data: { configured: true, reachable: true }, isError: false, isLoading: false }),
    useHomeAssistantEntities: () => ({
      data: [
        { entityId: 'binary_sensor.front_door', name: 'Front Door', domain: 'binary_sensor', deviceClass: 'door' },
        { entityId: 'binary_sensor.motion', name: 'Motion', domain: 'binary_sensor', deviceClass: 'motion' },
      ],
      isError: false,
      isLoading: false,
      error: null,
    }),
  }
})

vi.mock('@/hooks/useAlarmQueries', () => {
  return {
    useSensorsQuery: () => ({
      data: [{ id: 10, name: 'Existing', entityId: 'binary_sensor.motion', isActive: true, isEntryPoint: false, currentState: 'closed', lastTriggered: null }],
      isLoading: false,
    }),
  }
})

function createClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

describe('useImportSensorsModel', () => {
  it('computes row model with suggested entrypoint and import status', async () => {
    const client = createClient()
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useImportSensorsModel(), { wrapper })

    const doorEntity = result.current.visible.find((e) => e.entityId === 'binary_sensor.front_door')!

    const doorRow = result.current.getRowModel(doorEntity)
    expect(doorRow.alreadyImported).toBe(false)
    expect(doorRow.suggestedEntry).toBe(true)

    act(() => {
      result.current.setViewMode('imported')
    })

    const motionEntity = result.current.visible.find((e) => e.entityId === 'binary_sensor.motion')!
    const motionRow = result.current.getRowModel(motionEntity)
    expect(motionRow.alreadyImported).toBe(true)
    expect(motionRow.importedSensorId).toBe(10)
  })

  it('submits selected entities and invalidates sensors and alarm state queries', async () => {
    const client = createClient()
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useImportSensorsModel(), { wrapper })

    const doorEntity = result.current.visible.find((e) => e.entityId === 'binary_sensor.front_door')!

    act(() => {
      result.current.setEntityChecked(doorEntity as any, true)
    })

    await act(async () => {
      await result.current.submit()
    })

    expect(createSensor).toHaveBeenCalledWith(
      expect.objectContaining({
        entityId: 'binary_sensor.front_door',
        isActive: true,
        isEntryPoint: true,
      })
    )

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.sensors.all })
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.alarm.state })
    })

    expect(result.current.success?.count).toBe(1)
  })
})

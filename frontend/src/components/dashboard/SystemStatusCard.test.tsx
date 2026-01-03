import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { queryKeys } from '@/types'
import SystemStatusCard from '@/components/dashboard/SystemStatusCard'

vi.mock('@/hooks/useWebSocketStatus', () => {
  return { useWebSocketStatus: () => ({ data: 'connected' }) }
})

vi.mock('@/hooks/useAlarmQueries', () => {
  return {
    useAlarmStateQuery: () => ({ data: undefined, isFetching: false }),
    useSensorsQuery: () => ({ data: [], isFetching: false }),
    useRecentEventsQuery: () => ({ data: [], isFetching: false }),
  }
})

vi.mock('@/hooks/useHomeAssistant', () => {
  return { useHomeAssistantStatus: () => ({ data: { configured: true, reachable: true }, isError: false }) }
})

vi.mock('@/hooks/useMqtt', () => {
  return { useMqttStatusQuery: () => ({ data: { configured: true, enabled: true, connected: true }, isError: false }) }
})

vi.mock('@/hooks/useZwavejs', () => {
  return { useZwavejsStatusQuery: () => ({ data: { configured: true, enabled: true, connected: true }, isError: false }) }
})

vi.mock('@/hooks/useZigbee2mqtt', () => {
  return {
    useZigbee2mqttStatusQuery: () => ({
      data: {
        enabled: true,
        baseTopic: 'zigbee2mqtt',
        mqtt: { configured: true, enabled: true, connected: true },
        sync: { lastSyncAt: null, lastDeviceCount: null, lastError: null },
      },
      isError: false,
    }),
  }
})

vi.mock('@/hooks/useFrigate', () => {
  return {
    useFrigateStatusQuery: () => ({
      data: {
        enabled: true,
        eventsTopic: 'frigate/events',
        retentionSeconds: 0,
        available: true,
        mqtt: { configured: true, enabled: true, connected: true },
        ingest: { lastIngestAt: null, lastError: null },
      },
      isError: false,
    }),
  }
})

describe('SystemStatusCard', () => {
  it('refresh invalidates all relevant queries', async () => {
    const user = userEvent.setup()
    const { queryClient } = renderWithProviders(<SystemStatusCard />)
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    await user.click(screen.getByRole('button', { name: /refresh/i }))

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.alarm.state })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.sensors.all })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.events.recent })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.homeAssistant.status })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.mqtt.status })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.zwavejs.status })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.zigbee2mqtt.status })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.frigate.status })
  })

  it('shows placeholder timestamps when alarm state is missing', () => {
    renderWithProviders(<SystemStatusCard />)
    expect(screen.getByText('State Since')).toBeInTheDocument()
    expect(screen.getByText('Next Transition')).toBeInTheDocument()

    const placeholders = screen.getAllByText('—')
    expect(placeholders.length).toBeGreaterThanOrEqual(2)
  })
})

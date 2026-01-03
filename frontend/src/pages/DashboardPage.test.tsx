import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { queryKeys } from '@/types'
import DashboardPage from '@/pages/DashboardPage'

vi.mock('@/components/alarm', () => {
  return {
    AlarmPanel: () => {
      return <div>AlarmPanel</div>
    },
  }
})

vi.mock('@/components/dashboard/SystemStatusCard', () => {
  return { SystemStatusCard: () => <div>SystemStatusCard</div> }
})

vi.mock('@/components/providers/FeatureErrorBoundary', () => {
  return {
    FeatureErrorBoundary: (props: {
      feature: string
      children: React.ReactNode
      onRetry?: () => void
    }) => {
      if (props.feature === 'Latchpoint') {
        return (
          <button type="button" onClick={props.onRetry}>
            Retry Latchpoint
          </button>
        )
      }
      return <>{props.children}</>
    },
    default: (props: {
      feature: string
      children: React.ReactNode
      onRetry?: () => void
    }) => {
      if (props.feature === 'Latchpoint') {
        return (
          <button type="button" onClick={props.onRetry}>
            Retry Latchpoint
          </button>
        )
      }
      return <>{props.children}</>
    },
  }
})

describe('DashboardPage', () => {
  it('invalidates key queries when retrying alarm panel', async () => {
    const user = userEvent.setup()

    const { queryClient } = renderWithProviders(<DashboardPage />)
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    await user.click(screen.getByRole('button', { name: /retry latchpoint/i }))

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.alarm.state })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.sensors.all })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.events.recent })
  })
})

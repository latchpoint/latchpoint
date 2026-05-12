import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import type { PendingAction } from '@/types'

const mockUsePendingActionsQuery = vi.fn()
const mockMutate = vi.fn()

vi.mock('@/hooks/useAlarmQueries', () => ({
  usePendingActionsQuery: () => mockUsePendingActionsQuery(),
  useCancelPendingActionMutation: () => ({ mutate: mockMutate, isPending: false }),
}))

function makePendingAction(overrides: Partial<PendingAction> = {}): PendingAction {
  return {
    id: 1,
    ruleId: 10,
    ruleName: 'Front door entry',
    actionIndex: 0,
    actionPayload: { type: 'alarm_trigger', delay_seconds: 15 },
    delaySeconds: 15,
    scheduledAt: '2026-05-12T12:00:00Z',
    fireAt: new Date(Date.now() + 13_000).toISOString(),
    status: 'scheduled',
    cancelReason: '',
    firedAt: null,
    fireResult: null,
    armedStateAtSchedule: 'armed_away',
    actorUserEmail: null,
    createdAt: '2026-05-12T12:00:00Z',
    updatedAt: '2026-05-12T12:00:00Z',
    ...overrides,
  }
}

describe('PendingActionsCard', () => {
  it('renders nothing when the queue is empty', async () => {
    mockUsePendingActionsQuery.mockReturnValue({ data: [] })
    const { PendingActionsCard } = await import('./PendingActionsCard')
    const { container } = renderWithProviders(<PendingActionsCard />)
    expect(container.querySelector('[class*="rounded"]')).toBeNull()
  })

  it('renders queued actions with their rule name and a countdown', async () => {
    mockUsePendingActionsQuery.mockReturnValue({
      data: [makePendingAction({ ruleName: 'Door delay' })],
    })
    const { PendingActionsCard } = await import('./PendingActionsCard')
    renderWithProviders(<PendingActionsCard />)
    expect(screen.getByText('Pending Actions')).toBeInTheDocument()
    expect(screen.getByText('Trigger alarm')).toBeInTheDocument()
    expect(screen.getByText('Door delay')).toBeInTheDocument()
    // The countdown is a <strong> with "<N>s" — find any element that ends with "s".
    expect(screen.getByText(/^\d+s$/)).toBeInTheDocument()
  })

  it('shows the right label for send_notification actions', async () => {
    mockUsePendingActionsQuery.mockReturnValue({
      data: [
        makePendingAction({
          actionPayload: { type: 'send_notification', provider_id: 'p1', message: 'hi' },
        }),
      ],
    })
    const { PendingActionsCard } = await import('./PendingActionsCard')
    renderWithProviders(<PendingActionsCard />)
    expect(screen.getByText('Send notification')).toBeInTheDocument()
  })

  it('calls the cancel mutation when the user clicks Cancel', async () => {
    mockMutate.mockClear()
    mockUsePendingActionsQuery.mockReturnValue({
      data: [makePendingAction({ id: 42 })],
    })
    const { PendingActionsCard } = await import('./PendingActionsCard')
    renderWithProviders(<PendingActionsCard />)
    fireEvent.click(screen.getByRole('button', { name: /cancel pending action/i }))
    expect(mockMutate).toHaveBeenCalledWith(42)
  })
})

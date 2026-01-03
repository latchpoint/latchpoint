import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/render'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import EventsPage from '@/pages/EventsPage'

const refetch = vi.fn()
let model: any

vi.mock('@/features/events/hooks/useEventsPageModel', () => {
  return {
    useEventsPageModel: () => model,
  }
})

vi.mock('@/features/events/components/EventsFiltersCard', () => {
  return {
    EventsFiltersCard: (props: any) => (
      <div>
        <div>EventsFiltersCard</div>
        <button type="button" onClick={props.onRefresh}>
          Refresh
        </button>
        <button type="button" onClick={props.onClear}>
          Clear
        </button>
      </div>
    ),
  }
})

vi.mock('@/features/events/components/EventsHistoryCard', () => {
  return {
    EventsHistoryCard: (props: any) => (
      <div>
        <div>EventsHistoryCard</div>
        <div>Total: {props.total}</div>
      </div>
    ),
  }
})

describe('EventsPage', () => {
  beforeEach(() => {
    refetch.mockReset()
    model = {
      eventType: 'all',
      setEventType: vi.fn(),
      range: '24h',
      setRange: vi.fn(),
      clearFilters: vi.fn(),
      isLoading: false,
      isFetching: false,
      error: null,
      events: [],
      total: 0,
      page: 1,
      totalPages: 1,
      hasNext: false,
      hasPrevious: false,
      goToNextPage: vi.fn(),
      goToPreviousPage: vi.fn(),
      eventsQuery: { refetch },
    }
  })

  it('wires refresh and clear handlers', async () => {
    const user = userEvent.setup()
    renderWithProviders(<EventsPage />)

    expect(screen.getByText('EventsFiltersCard')).toBeInTheDocument()
    expect(screen.getByText('EventsHistoryCard')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /refresh/i }))
    expect(refetch).toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /clear/i }))
    expect(model.clearFilters).toHaveBeenCalled()
  })
})


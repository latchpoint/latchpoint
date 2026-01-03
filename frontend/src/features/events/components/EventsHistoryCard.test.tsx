import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { EventsHistoryCard } from '@/features/events/components/EventsHistoryCard'
import type { AlarmEvent } from '@/types'

vi.mock('@/features/events/components/EventRow', () => {
  return {
    EventRow: ({ event }: { event: AlarmEvent }) => <div>Event {event.id}</div>,
  }
})

function makeEvent(id: number): AlarmEvent {
  return {
    id,
    eventType: 'armed',
    stateFrom: null,
    stateTo: null,
    timestamp: '2025-01-01T00:00:00Z',
    userId: null,
    codeId: null,
    sensorId: null,
    metadata: {},
  }
}

describe('EventsHistoryCard', () => {
  it('shows loading state', () => {
    renderWithProviders(
      <EventsHistoryCard
        events={[]}
        total={0}
        page={1}
        totalPages={1}
        hasNext={false}
        hasPrevious={false}
        error={null}
        isLoading={true}
        isFetching={false}
        onNextPage={() => {}}
        onPreviousPage={() => {}}
      />
    )

    expect(screen.getByText(/loading events/i)).toBeInTheDocument()
  })

  it('shows empty state when no events', () => {
    renderWithProviders(
      <EventsHistoryCard
        events={[]}
        total={0}
        page={1}
        totalPages={1}
        hasNext={false}
        hasPrevious={false}
        error={null}
        isLoading={false}
        isFetching={false}
        onNextPage={() => {}}
        onPreviousPage={() => {}}
      />
    )

    expect(screen.getByText(/no events/i)).toBeInTheDocument()
  })

  it('renders events and pagination controls', async () => {
    const user = userEvent.setup()
    const onNext = vi.fn()
    const onPrev = vi.fn()

    renderWithProviders(
      <EventsHistoryCard
        events={[makeEvent(1), makeEvent(2)]}
        total={25}
        page={2}
        totalPages={3}
        hasNext={true}
        hasPrevious={true}
        error={null}
        isLoading={false}
        isFetching={false}
        onNextPage={onNext}
        onPreviousPage={onPrev}
      />
    )

    expect(screen.getByText('Event 1')).toBeInTheDocument()
    expect(screen.getByText('Event 2')).toBeInTheDocument()
    expect(screen.getByText(/page 2 of 3/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /next/i }))
    await user.click(screen.getByRole('button', { name: /prev/i }))
    expect(onNext).toHaveBeenCalledTimes(1)
    expect(onPrev).toHaveBeenCalledTimes(1)
  })

  it('disables pagination buttons when unavailable or fetching', () => {
    renderWithProviders(
      <EventsHistoryCard
        events={[makeEvent(1)]}
        total={2}
        page={1}
        totalPages={2}
        hasNext={false}
        hasPrevious={false}
        error={null}
        isLoading={false}
        isFetching={true}
        onNextPage={() => {}}
        onPreviousPage={() => {}}
      />
    )

    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled()
  })

  it('shows error message', () => {
    renderWithProviders(
      <EventsHistoryCard
        events={[]}
        total={0}
        page={1}
        totalPages={1}
        hasNext={false}
        hasPrevious={false}
        error="Bad things happened"
        isLoading={false}
        isFetching={false}
        onNextPage={() => {}}
        onPreviousPage={() => {}}
      />
    )

    expect(screen.getByText(/bad things happened/i)).toBeInTheDocument()
  })
})


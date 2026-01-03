import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { EventsFiltersCard } from '@/features/events/components/EventsFiltersCard'

describe('EventsFiltersCard', () => {
  it('calls onRefresh and onClear, and disables actions while loading', async () => {
    const user = userEvent.setup()
    const onRefresh = vi.fn()
    const onClear = vi.fn()

    const { rerender } = renderWithProviders(
      <EventsFiltersCard
        eventType=""
        setEventType={() => {}}
        range={{ start: '', end: '' }}
        setRange={() => {}}
        onRefresh={onRefresh}
        onClear={onClear}
        isLoading={false}
      />
    )

    await user.click(screen.getByRole('button', { name: /refresh/i }))
    await user.click(screen.getByRole('button', { name: /clear/i }))
    expect(onRefresh).toHaveBeenCalledTimes(1)
    expect(onClear).toHaveBeenCalledTimes(1)

    rerender(
      <EventsFiltersCard
        eventType=""
        setEventType={() => {}}
        range={{ start: '', end: '' }}
        setRange={() => {}}
        onRefresh={onRefresh}
        onClear={onClear}
        isLoading={true}
      />
    )

    expect(screen.getByRole('button', { name: /refresh/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /clear/i })).toBeDisabled()
  })

  it('updates event type via the select', async () => {
    const user = userEvent.setup()
    const setEventType = vi.fn()

    renderWithProviders(
      <EventsFiltersCard
        eventType=""
        setEventType={setEventType}
        range={{ start: '', end: '' }}
        setRange={() => {}}
        onRefresh={() => {}}
        onClear={() => {}}
        isLoading={false}
      />
    )

    await user.selectOptions(screen.getByLabelText(/event type/i), ['armed'])
    expect(setEventType).toHaveBeenCalledWith('armed')
  })
})


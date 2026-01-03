import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { render } from '@testing-library/react'
import { RulesPageActions } from '@/features/rules/components/RulesPageActions'

describe('RulesPageActions', () => {
  it('calls handlers and includes Test Rules link', async () => {
    const user = userEvent.setup()
    const onSyncEntities = vi.fn()
    const onSyncZwavejsEntities = vi.fn()
    const onRunRules = vi.fn()
    const onRefresh = vi.fn()

    render(
      <MemoryRouter>
        <RulesPageActions
          isSaving={false}
          onSyncEntities={onSyncEntities}
          onSyncZwavejsEntities={onSyncZwavejsEntities}
          onRunRules={onRunRules}
          onRefresh={onRefresh}
        />
      </MemoryRouter>
    )

    await user.click(screen.getByRole('button', { name: /sync ha entities/i }))
    await user.click(screen.getByRole('button', { name: /sync z-wave entities/i }))
    await user.click(screen.getByRole('button', { name: /run rules/i }))
    await user.click(screen.getByRole('button', { name: /refresh/i }))

    expect(onSyncEntities).toHaveBeenCalledTimes(1)
    expect(onSyncZwavejsEntities).toHaveBeenCalledTimes(1)
    expect(onRunRules).toHaveBeenCalledTimes(1)
    expect(onRefresh).toHaveBeenCalledTimes(1)

    expect(screen.getByRole('link', { name: /test rules/i })).toBeInTheDocument()
  })
})


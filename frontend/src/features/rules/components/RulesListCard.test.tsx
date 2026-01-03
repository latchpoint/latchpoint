import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RulesListCard } from '@/features/rules/components/RulesListCard'

vi.mock('@/features/rules/builder', () => {
  return {
    countThenActions: () => 2,
  }
})

describe('RulesListCard', () => {
  it('shows empty state when no rules', () => {
    render(<RulesListCard isLoading={false} rules={[]} onEdit={() => {}} />)
    expect(screen.getByText(/no rules yet/i)).toBeInTheDocument()
  })

  it('renders rules and calls onEdit', async () => {
    const user = userEvent.setup()
    const onEdit = vi.fn()
    render(
      <RulesListCard
        isLoading={false}
        rules={[
          {
            id: 1,
            name: 'Rule 1',
            kind: 'trigger',
            enabled: true,
            priority: 0,
            schemaVersion: 1,
            cooldownSeconds: null,
            entityIds: ['binary_sensor.front_door'],
            definition: { then: [] },
          } as any,
        ]}
        onEdit={onEdit}
      />
    )

    expect(screen.getByText(/existing rules/i)).toBeInTheDocument()
    expect(screen.getByText(/rule 1/i)).toBeInTheDocument()
    expect(screen.getByText(/actions: 2/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /edit/i }))
    expect(onEdit).toHaveBeenCalled()
  })
})


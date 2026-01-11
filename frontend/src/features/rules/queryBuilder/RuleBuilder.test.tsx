import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import type { Rule } from '@/types/rules'

vi.mock('./ActionsEditor', () => ({ ActionsEditor: () => <div>ActionsEditor</div> }))
vi.mock('./RuleQueryBuilder', () => ({ RuleQueryBuilder: () => <div>RuleQueryBuilder</div> }))

describe('RuleBuilder', () => {
  it('imports', async () => {
    const mod = await import('./RuleBuilder')
    expect(mod).toBeTruthy()
  })

  it('disables save for time-only rules (guardrail)', async () => {
    const { RuleBuilder } = await import('./RuleBuilder')

    const rule = {
      id: 1,
      name: 'Time only',
      kind: 'trigger',
      enabled: true,
      priority: 100,
      schemaVersion: 1,
      definition: {
        when: { op: 'time_in_range', start: '22:00', end: '06:00' },
        then: [{ type: 'alarm_trigger' }],
      },
      cooldownSeconds: null,
      createdBy: null,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
      entityIds: [],
    } as any satisfies Rule

    renderWithProviders(
      <RuleBuilder
        rule={rule}
        entities={[]}
        onSave={vi.fn()}
        onCancel={() => {}}
        isSaving={false}
      />
    )

    expect(screen.getByText(/time of day must be combined/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /update rule/i })).toBeDisabled()
  })
})

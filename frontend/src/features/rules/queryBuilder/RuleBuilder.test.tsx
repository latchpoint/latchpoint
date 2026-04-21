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
      stopProcessing: false,
      stopGroup: '',
      cooldownSeconds: null,
      createdBy: null,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
      entityIds: [],
    } satisfies Rule

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

  it('initializes from a seed in create mode with the copied values', async () => {
    const { RuleBuilder } = await import('./RuleBuilder')

    const seed = {
      name: 'My Rule (copy)',
      kind: 'trigger' as const,
      enabled: true,
      priority: 77,
      stopProcessing: false,
      stopGroup: '',
      schemaVersion: 1,
      definition: { when: null, then: [{ type: 'alarm_trigger' }] },
      cooldownSeconds: 45,
    }

    renderWithProviders(
      <RuleBuilder
        rule={null}
        seed={seed}
        entities={[]}
        onSave={vi.fn()}
        onCancel={() => {}}
        isSaving={false}
      />
    )

    expect(screen.getByText(/new rule \(copied\)/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/name/i)).toHaveValue('My Rule (copy)')
    expect(screen.getByLabelText(/priority/i)).toHaveValue(77)
    expect(screen.getByLabelText(/cooldown/i)).toHaveValue(45)
    expect(screen.getByRole('button', { name: /create rule/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /delete rule/i })).not.toBeInTheDocument()
  })
})

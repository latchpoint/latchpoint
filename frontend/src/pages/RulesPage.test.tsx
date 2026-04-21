import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/render'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RulesPage from '@/pages/RulesPage'

let rulesLoading = false
let entitiesLoading = false

const syncHa = vi.fn().mockResolvedValue({ notice: 'synced' })
const cloneRuleMock = vi.fn((rule: any) => ({
  name: `${rule.name} (copy)`,
  kind: rule.kind,
  enabled: true,
  priority: 100,
  stopProcessing: false,
  stopGroup: '',
  schemaVersion: 1,
  definition: { when: null, then: [] },
  cooldownSeconds: null,
}))

let lastBuilderProps: any = null

vi.mock('@/features/rules/queryBuilder', () => {
  return {
    RuleBuilder: (props: any) => {
      lastBuilderProps = props
      return <div>RuleBuilder</div>
    },
    RulesPageActions: (props: any) => (
      <div>
        <button type="button" onClick={props.onSyncHaEntities}>
          Sync HA
        </button>
      </div>
    ),
    cloneRule: (rule: any, existing: any) => cloneRuleMock(rule, existing),
  }
})

vi.mock('@/hooks/useRulesQueries', () => {
  return {
    useRulesQuery: () => ({ data: [{ id: 1, name: 'R1', kind: 'trigger', enabled: true }], isLoading: rulesLoading, error: null }),
    useEntitiesQuery: () => ({ data: [{ entityId: 'binary_sensor.door', name: 'Door' }], isLoading: entitiesLoading, error: null }),
    useSaveRuleMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useDeleteRuleMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useSyncEntitiesMutation: () => ({ isPending: false, mutateAsync: syncHa }),
    useRunRulesMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
  }
})

vi.mock('@/hooks/useZwavejs', () => {
  return {
    useSyncZwavejsEntitiesMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
  }
})

vi.mock('@/features/rules/components/RulesPageNotices', () => {
  return { RulesPageNotices: () => <div>RulesPageNotices</div> }
})

describe('RulesPage', () => {
  beforeEach(() => {
    rulesLoading = false
    entitiesLoading = false
    syncHa.mockReset().mockResolvedValue({ notice: 'synced' })
    cloneRuleMock.mockClear()
    lastBuilderProps = null
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  it('renders builder and wires Sync HA action', async () => {
    const user = userEvent.setup()
    renderWithProviders(<RulesPage />)

    expect(screen.getByText('RuleBuilder')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /sync ha/i }))
    expect(syncHa).toHaveBeenCalled()
  })

  it('shows loading page while queries are loading', () => {
    rulesLoading = true
    renderWithProviders(<RulesPage />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('copies a rule into the builder as a seed when confirmed', async () => {
    const user = userEvent.setup()
    const confirmMock = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmMock)

    renderWithProviders(<RulesPage />)

    await user.click(screen.getByRole('button', { name: /copy rule r1/i }))

    expect(confirmMock).toHaveBeenCalledWith('Copy rule "R1"?')
    expect(cloneRuleMock).toHaveBeenCalledTimes(1)
    expect(cloneRuleMock.mock.calls[0][0]).toMatchObject({ id: 1, name: 'R1' })
    expect(lastBuilderProps).not.toBeNull()
    expect(lastBuilderProps.seed).toMatchObject({ name: 'R1 (copy)' })
    expect(lastBuilderProps.rule).toBeNull()
  })

  it('does not copy when the user cancels the confirmation', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('confirm', vi.fn(() => false))

    renderWithProviders(<RulesPage />)

    await user.click(screen.getByRole('button', { name: /copy rule r1/i }))

    expect(cloneRuleMock).not.toHaveBeenCalled()
    expect(lastBuilderProps?.seed ?? null).toBeNull()
  })
})

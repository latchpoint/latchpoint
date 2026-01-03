import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/render'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RulesBuilderPage from '@/pages/RulesBuilderPage'

let rulesLoading = false
let entitiesLoading = false

const syncHa = vi.fn().mockResolvedValue({ notice: 'synced' })

vi.mock('@/features/rules/queryBuilder', () => {
  return {
    RuleBuilderV2: () => <div>RuleBuilderV2</div>,
    RulesBuilderPageActions: (props: any) => (
      <div>
        <button type="button" onClick={props.onSyncHaEntities}>
          Sync HA
        </button>
      </div>
    ),
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

describe('RulesBuilderPage', () => {
  beforeEach(() => {
    rulesLoading = false
    entitiesLoading = false
    syncHa.mockReset().mockResolvedValue({ notice: 'synced' })
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  it('renders builder and wires Sync HA action', async () => {
    const user = userEvent.setup()
    renderWithProviders(<RulesBuilderPage />)

    expect(screen.getByText('RuleBuilderV2')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /sync ha/i }))
    expect(syncHa).toHaveBeenCalled()
  })

  it('shows loading page while queries are loading', () => {
    rulesLoading = true
    renderWithProviders(<RulesBuilderPage />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })
})


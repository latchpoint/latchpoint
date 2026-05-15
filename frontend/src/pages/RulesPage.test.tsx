import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test/render'
import { screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RulesPage from '@/pages/RulesPage'

let rulesLoading = false
let entitiesLoading = false

const DEFAULT_RULES = [{ id: 1, name: 'R1', kind: 'trigger', enabled: true }]
let rulesList: any[] = [...DEFAULT_RULES]

const syncHa = vi.fn().mockResolvedValue({ notice: 'synced' })
const saveAsync = vi.fn()
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
    useRulesQuery: () => ({ data: rulesList, isLoading: rulesLoading, error: null }),
    useEntitiesQuery: () => ({ data: [{ entityId: 'binary_sensor.door', name: 'Door' }], isLoading: entitiesLoading, error: null }),
    useSaveRuleMutation: () => ({ isPending: false, mutateAsync: saveAsync }),
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
    rulesList = [...DEFAULT_RULES]
    syncHa.mockReset().mockResolvedValue({ notice: 'synced' })
    saveAsync.mockReset()
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

  const minimalSavePayload = {
    name: 'New Rule',
    enabled: true,
    priority: 100,
    stopProcessing: false,
    stopGroup: '',
    schemaVersion: 1,
    definition: { when: null, then: [] },
    cooldownSeconds: null,
  }

  it('keeps the newly created rule selected after Save (no reset to new-rule form)', async () => {
    const newRule = { id: 42, name: 'New Rule', kind: 'trigger', enabled: true }
    saveAsync.mockImplementation(async () => {
      // Mimic the real flow: useSaveRuleMutation.onSuccess awaits the rules
      // refetch before mutateAsync resolves, so the rules list already
      // includes the freshly-created rule by the time we set selectedRuleId.
      rulesList = [...DEFAULT_RULES, newRule]
      return { data: newRule, notice: 'Rule created.' }
    })

    renderWithProviders(<RulesPage />)

    expect(lastBuilderProps.rule).toBeNull()

    await act(async () => {
      await lastBuilderProps.onSave(minimalSavePayload)
    })

    expect(saveAsync).toHaveBeenCalledWith({ id: null, payload: minimalSavePayload })
    expect(lastBuilderProps.rule).toMatchObject({ id: 42 })
    expect(lastBuilderProps.seed).toBeNull()
  })

  it('keeps the existing rule selected after Save during an update', async () => {
    saveAsync.mockResolvedValue({
      data: { id: 1, name: 'R1', kind: 'trigger', enabled: true },
      notice: 'Rule updated.',
    })

    renderWithProviders(<RulesPage />, { route: '/?edit=1' })

    expect(lastBuilderProps.rule).toMatchObject({ id: 1 })

    await act(async () => {
      await lastBuilderProps.onSave({ ...minimalSavePayload, name: 'R1' })
    })

    expect(saveAsync).toHaveBeenCalledWith({ id: 1, payload: { ...minimalSavePayload, name: 'R1' } })
    expect(lastBuilderProps.rule).toMatchObject({ id: 1 })
    expect(lastBuilderProps.rule).not.toBeNull()
  })
})

import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import RulesPage from '@/pages/RulesPage'

let model: any

vi.mock('@/features/rules/hooks/useRulesPageModel', () => {
  return { useRulesPageModel: () => model }
})

vi.mock('@/features/rules/components/RulesPageActions', () => {
  return {
    RulesPageActions: (props: any) => (
      <div>
        <button type="button" onClick={props.onSyncEntities}>
          Sync HA
        </button>
      </div>
    ),
  }
})

vi.mock('@/features/rules/components/RulesPageNotices', () => {
  return { RulesPageNotices: () => <div>RulesPageNotices</div> }
})

vi.mock('@/features/rules/components/RuleEditorCard', () => {
  return { RuleEditorCard: () => <div>RuleEditorCard</div> }
})

vi.mock('@/features/rules/components/RulesListCard', () => {
  return { RulesListCard: () => <div>RulesListCard</div> }
})

describe('RulesPage', () => {
  beforeEach(() => {
    model = {
      isSaving: false,
      onSyncEntities: vi.fn(),
      onSyncZwavejsEntities: vi.fn(),
      onRunRules: vi.fn(),
      onRefresh: vi.fn(),
      notice: null,
      displayedError: null,
      editingId: null,
      ruleKinds: [],
      name: '',
      setName: vi.fn(),
      kind: '',
      setKind: vi.fn(),
      enabled: true,
      setEnabled: vi.fn(),
      priority: 0,
      setPriority: vi.fn(),
      advanced: false,
      setAdvanced: vi.fn(),
      cooldownSeconds: null,
      setCooldownSeconds: vi.fn(),
      entityIdsText: '',
      setEntityIdsText: vi.fn(),
      derivedEntityIds: [],
      derivedEntityIdsText: '',
      builderDefinitionText: '',
      definitionText: '',
      setDefinitionText: vi.fn(),
      entitiesLength: 0,
      whenOperator: 'any',
      setWhenOperator: vi.fn(),
      forSecondsText: '',
      setForSecondsText: vi.fn(),
      entitySourceFilter: 'all',
      setEntitySourceFilter: vi.fn(),
      conditions: [],
      setConditions: vi.fn(),
      alarmStatePickerByConditionId: new Map(),
      setAlarmStatePickerByConditionId: vi.fn(),
      frigateCameraPickerByConditionId: new Map(),
      setFrigateCameraPickerByConditionId: vi.fn(),
      frigateZonePickerByConditionId: new Map(),
      setFrigateZonePickerByConditionId: vi.fn(),
      actions: [],
      setActions: vi.fn(),
      targetEntityPickerByActionId: new Map(),
      setTargetEntityPickerByActionId: vi.fn(),
      updateHaActionTargetEntityIds: vi.fn(),
      entityIdOptions: [],
      entityIdSet: new Set(),
      frigateOptions: null,
      onSubmit: vi.fn(),
      onCancel: vi.fn(),
      onDelete: vi.fn(),
      isLoading: false,
      rules: [],
      onStartEdit: vi.fn(),
    }
  })

  it('wires actions to the model', async () => {
    const user = userEvent.setup()
    renderWithProviders(<RulesPage />)

    expect(screen.getByText('RulesPageNotices')).toBeInTheDocument()
    expect(screen.getByText('RuleEditorCard')).toBeInTheDocument()
    expect(screen.getByText('RulesListCard')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /sync ha/i }))
    expect(model.onSyncEntities).toHaveBeenCalled()
  })
})


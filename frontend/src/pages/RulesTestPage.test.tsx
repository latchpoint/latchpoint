import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import userEvent from '@testing-library/user-event'
import RulesTestPage from '@/pages/RulesTestPage'

let model: any

vi.mock('@/features/rulesTest/hooks/useRulesTestPageModel', () => {
  return { useRulesTestPageModel: () => model }
})

vi.mock('@/features/rulesTest/components/RulesTestHeaderActions', () => {
  return {
    RulesTestHeaderActions: (props: any) => (
      <div>
        <button type="button" onClick={props.onSyncHa} disabled={props.disabled}>
          Sync HA
        </button>
      </div>
    ),
  }
})

vi.mock('@/features/rulesTest/components/RulesTestModeToggle', () => {
  return { RulesTestModeToggle: () => <div>RulesTestModeToggle</div> }
})

vi.mock('@/features/rulesTest/components/ScenarioRowsEditor', () => {
  return { ScenarioRowsEditor: () => <div>ScenarioRowsEditor</div> }
})

vi.mock('@/features/rulesTest/components/RulesTestResults', () => {
  return { RulesTestResults: () => <div>RulesTestResults</div> }
})

vi.mock('@/features/rulesTest/components/DeltaChangeControls', () => {
  return { DeltaChangeControls: () => <div>DeltaChangeControls</div> }
})

vi.mock('@/features/rulesTest/components/SimulationOptionsBar', () => {
  return { SimulationOptionsBar: () => <div>SimulationOptionsBar</div> }
})

vi.mock('@/features/rulesTest/components/SavedScenariosCard', () => {
  return { SavedScenariosCard: () => <div>SavedScenariosCard</div> }
})

describe('RulesTestPage', () => {
  beforeEach(() => {
    model = {
      displayedError: null,
      isLoading: false,
      isRunning: false,
      syncEntities: vi.fn(),
      syncZwavejsEntities: vi.fn(),
      refreshEntities: vi.fn(),
      mode: 'scenario',
      setMode: vi.fn(),
      rows: [],
      setRows: vi.fn(),
      entityIdOptions: [],
      entitiesById: new Map(),
      setRowEntityId: vi.fn(),
      deltaEntityId: '',
      setDeltaEntityId: vi.fn(),
      deltaState: '',
      setDeltaState: vi.fn(),
      simulateDelta: vi.fn(),
      assumeForSeconds: false,
      setAssumeForSeconds: vi.fn(),
      alarmState: 'disarmed',
      setAlarmState: vi.fn(),
      simulate: vi.fn(),
      scenarioName: '',
      setScenarioName: vi.fn(),
      savedScenarios: [],
      selectedScenario: null,
      setSelectedScenario: vi.fn(),
      saveScenario: vi.fn(),
      loadScenario: vi.fn(),
      deleteScenario: vi.fn(),
      result: null,
      baselineResult: null,
    }
  })

  it('wires header action callbacks', async () => {
    const user = userEvent.setup()
    renderWithProviders(<RulesTestPage />)

    expect(screen.getByText('RulesTestModeToggle')).toBeInTheDocument()
    expect(screen.getByText('ScenarioRowsEditor')).toBeInTheDocument()
    expect(screen.getByText('SimulationOptionsBar')).toBeInTheDocument()
    expect(screen.getByText('SavedScenariosCard')).toBeInTheDocument()
    expect(screen.getByText('RulesTestResults')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /sync ha/i }))
    expect(model.syncEntities).toHaveBeenCalled()
  })
})


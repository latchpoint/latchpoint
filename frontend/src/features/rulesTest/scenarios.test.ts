import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createScenarioRow, loadSavedScenarios, saveSavedScenarios } from '@/features/rulesTest/scenarios'
import { StorageKeys } from '@/lib/constants'

describe('rulesTest/scenarios', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.spyOn(Date, 'now').mockReturnValue(123)
    vi.spyOn(Math, 'random').mockReturnValue(0.5)
  })

  it('creates a scenario row with stable id and defaults', () => {
    const row = createScenarioRow()
    expect(row).toEqual({ id: expect.stringContaining('123-'), entityId: '', state: 'on' })
  })

  it('loads empty list for missing/invalid data', () => {
    expect(loadSavedScenarios()).toEqual([])

    localStorage.setItem(StorageKeys.RULES_TEST_SCENARIOS, '{"nope":true}')
    expect(loadSavedScenarios()).toEqual([])

    localStorage.setItem(StorageKeys.RULES_TEST_SCENARIOS, 'not json')
    expect(loadSavedScenarios()).toEqual([])
  })

  it('saves and loads scenarios', () => {
    saveSavedScenarios([{ name: 'A', rows: [{ id: '1', entityId: 'x', state: 'on' }], assumeForSeconds: '5' }])
    expect(loadSavedScenarios()).toEqual([{ name: 'A', rows: [{ id: '1', entityId: 'x', state: 'on' }], assumeForSeconds: '5' }])
  })
})


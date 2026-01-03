import { StorageKeys } from '@/lib/constants'

export type ScenarioRow = { id: string; entityId: string; state: string }

export type SavedScenario = {
  name: string
  rows: ScenarioRow[]
  assumeForSeconds: string
}

function uniqueId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const storageKey = StorageKeys.RULES_TEST_SCENARIOS

export function createScenarioRow(): ScenarioRow {
  return { id: uniqueId(), entityId: '', state: 'on' }
}

export function loadSavedScenarios(): SavedScenario[] {
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((s) => s && typeof s.name === 'string' && Array.isArray(s.rows)) as SavedScenario[]
  } catch {
    return []
  }
}

export function saveSavedScenarios(scenarios: SavedScenario[]) {
  localStorage.setItem(storageKey, JSON.stringify(scenarios))
}

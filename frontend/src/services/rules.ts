import api from './api'
import type { Rule, RuleRunResult, RuleSimulateRequest, RuleSimulateResult, RuleDefinition } from '@/types'
import { apiEndpoints } from './endpoints'

export const rulesService = {
  async list(params?: { kind?: Rule['kind']; enabled?: boolean }): Promise<Rule[]> {
    return api.get<Rule[]>(apiEndpoints.rules.all, params)
  },

  async run(): Promise<RuleRunResult> {
    return api.post<RuleRunResult>(apiEndpoints.rules.run, {})
  },

  async simulate(payload: RuleSimulateRequest): Promise<RuleSimulateResult> {
    return api.post<RuleSimulateResult>(apiEndpoints.rules.simulate, payload)
  },

  async create(rule: {
    name: string
    kind?: Rule['kind']  // Optional - auto-derived from actions by backend
    enabled: boolean
    priority: number
    schemaVersion: number
    definition: RuleDefinition
    cooldownSeconds?: number | null
    entityIds?: string[]
  }): Promise<Rule> {
    return api.post<Rule>(apiEndpoints.rules.all, rule)
  },

  async update(id: number, rule: Partial<Omit<Rule, 'id'>>): Promise<Rule> {
    return api.patch<Rule>(apiEndpoints.rules.detail(id), rule)
  },

  async delete(id: number): Promise<void> {
    return api.delete(apiEndpoints.rules.detail(id))
  },
}

export default rulesService

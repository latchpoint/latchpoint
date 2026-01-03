import type { RuleDefinition } from './ruleDefinition'

export type RuleKind = 'trigger' | 'disarm' | 'arm' | 'suppress' | 'escalate'

export interface Entity {
  id: number
  entityId: string
  domain: string
  name: string
  deviceClass: string | null
  lastState: string | null
  lastChanged: string | null
  lastSeen: string | null
  attributes: Record<string, unknown>
  source: string
  createdAt: string
  updatedAt: string
}

export interface Rule {
  id: number
  name: string
  kind: RuleKind
  enabled: boolean
  priority: number
  schemaVersion: number
  definition: RuleDefinition
  cooldownSeconds: number | null
  entityIds: string[]
  createdBy: string | null
  createdAt: string
  updatedAt: string
}

export interface RuleRunResult {
  evaluated: number
  fired: number
  scheduled: number
  skippedCooldown: number
  errors: number
}

export interface RuleSimulateRequest {
  entityStates: Record<string, string>
  assumeForSeconds?: number
  alarmState?: string
}

export interface RuleSimulateForInfo {
  seconds: number
  status: string
  assumedForSeconds?: number
}

export interface RuleSimulateEntry {
  id: number
  name: string
  kind: RuleKind
  priority: number
  matched: boolean
  for?: RuleSimulateForInfo | null
  trace: Record<string, unknown>
  actions: unknown[]
}

export interface RuleSimulateResult {
  timestamp: string
  summary: { evaluated: number; matched: number; wouldSchedule: number }
  matchedRules: RuleSimulateEntry[]
  nonMatchingRules: RuleSimulateEntry[]
}

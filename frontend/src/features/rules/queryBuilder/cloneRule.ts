import type { Rule, RuleKind } from '@/types/rules'
import type { RuleDefinition } from '@/types/ruleDefinition'

export interface RuleSeed {
  name: string
  kind: RuleKind
  enabled: boolean
  priority: number
  stopProcessing: boolean
  stopGroup: string
  schemaVersion: number
  definition: RuleDefinition
  cooldownSeconds: number | null
}

export function disambiguateCopyName(original: string, existing: readonly string[]): string {
  const existingSet = new Set(existing)
  const firstCandidate = `${original} (copy)`
  if (!existingSet.has(firstCandidate)) return firstCandidate
  let n = 2
  while (existingSet.has(`${original} (copy ${n})`)) {
    n += 1
  }
  return `${original} (copy ${n})`
}

function deepCloneDefinition(definition: RuleDefinition): RuleDefinition {
  if (typeof structuredClone === 'function') {
    return structuredClone(definition)
  }
  return JSON.parse(JSON.stringify(definition)) as RuleDefinition
}

export function cloneRule(rule: Rule, existingNames: readonly string[]): RuleSeed {
  return {
    name: disambiguateCopyName(rule.name, existingNames),
    kind: rule.kind,
    enabled: rule.enabled,
    priority: rule.priority,
    stopProcessing: rule.stopProcessing,
    stopGroup: rule.stopGroup,
    schemaVersion: rule.schemaVersion,
    definition: deepCloneDefinition(rule.definition),
    cooldownSeconds: rule.cooldownSeconds,
  }
}

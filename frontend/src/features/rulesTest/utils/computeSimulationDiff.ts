import type { RuleSimulateResult } from '@/types'

type Status = 'matched' | 'would_schedule' | 'not_matched'

export type SimulationDiffEntry = {
  id: number
  name: string
  kind: string
  priority: number
  status: Status
  trace: unknown
  actions: unknown
  forInfo?: unknown
}

export type SimulationDiff = {
  changedRules: Array<{ id: number; from: SimulationDiffEntry; to: SimulationDiffEntry }>
}

export function computeSimulationDiff(base: RuleSimulateResult, changed: RuleSimulateResult): SimulationDiff {
  const normalize = (res: RuleSimulateResult) => {
    const out = new Map<number, SimulationDiffEntry>()
    const matchedRules = Array.isArray(res.matchedRules) ? res.matchedRules : []
    const nonMatching = Array.isArray(res.nonMatchingRules) ? res.nonMatchingRules : []
    for (const r of matchedRules as any[]) {
      const status: Status =
        r.matched === true ? 'matched' : r.for?.status === 'would_schedule' ? 'would_schedule' : 'not_matched'
      out.set(r.id, {
        id: r.id,
        name: r.name,
        kind: r.kind,
        priority: r.priority,
        status,
        trace: r.trace,
        actions: r.actions,
        forInfo: r.for,
      })
    }
    for (const r of nonMatching as any[]) {
      if (out.has(r.id)) continue
      out.set(r.id, {
        id: r.id,
        name: r.name,
        kind: r.kind,
        priority: r.priority,
        status: 'not_matched',
        trace: r.trace,
        actions: r.actions,
      })
    }
    return out
  }

  const baseMap = normalize(base)
  const changedMap = normalize(changed)
  const changedRules: Array<{ id: number; from: SimulationDiffEntry; to: SimulationDiffEntry }> = []

  const allIds = new Set<number>([...baseMap.keys(), ...changedMap.keys()])
  for (const id of allIds) {
    const from = baseMap.get(id)
    const to = changedMap.get(id)
    if (!from || !to) continue
    if (from.status !== to.status) changedRules.push({ id, from, to })
  }

  changedRules.sort((a, b) => {
    if (a.to.priority !== b.to.priority) return b.to.priority - a.to.priority
    return a.to.name.localeCompare(b.to.name)
  })

  return { changedRules }
}


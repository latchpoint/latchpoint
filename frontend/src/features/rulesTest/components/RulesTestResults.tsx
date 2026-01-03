import { useMemo, useState } from 'react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import type { RuleSimulateResult } from '@/types'
import { computeSimulationDiff } from '@/features/rulesTest/utils/computeSimulationDiff'
import { RulesTestRulesList, type SimulatedRule } from '@/features/rulesTest/components/results/RulesTestRulesList'
import { RulesTestChangesCard } from '@/features/rulesTest/components/results/RulesTestChangesCard'
import { RulesTestResultsToolbar } from '@/features/rulesTest/components/results/RulesTestResultsToolbar'

type Props = {
  mode: 'scenario' | 'delta'
  result: RuleSimulateResult | null
  baselineResult: RuleSimulateResult | null
}

function normalizeRules(list: unknown): SimulatedRule[] {
  return Array.isArray(list) ? (list as SimulatedRule[]) : []
}

export function RulesTestResults({ mode, result, baselineResult }: Props) {
  const [ruleSearch, setRuleSearch] = useState('')
  const [showOnlyMatched, setShowOnlyMatched] = useState(false)

  const diff = useMemo(() => {
    if (!baselineResult || !result) return null
    return computeSimulationDiff(baselineResult, result)
  }, [baselineResult, result])

  const matchedRules = useMemo(() => {
    const all = normalizeRules(result?.matchedRules)
    return all.filter((r) => r.matched === true)
  }, [result])

  const scheduledForRules = useMemo(() => {
    const all = normalizeRules(result?.matchedRules)
    return all.filter((r) => r.matched !== true && r.for?.status === 'would_schedule')
  }, [result])

  const nonMatchingRules = useMemo(() => normalizeRules(result?.nonMatchingRules), [result])

  const filterRuleList = useMemo(() => {
    const needle = ruleSearch.trim().toLowerCase()
    return (list: SimulatedRule[]) => {
      const base = showOnlyMatched ? list.filter((r) => r.matched === true) : list
      if (!needle) return base
      return base.filter((r) => r.name.toLowerCase().includes(needle))
    }
  }, [ruleSearch, showOnlyMatched])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Results</CardTitle>
        <CardDescription>
          {result?.summary
            ? `Evaluated ${result.summary.evaluated}, matched ${result.summary.matched}, would schedule ${result.summary.wouldSchedule}.`
            : 'Run a simulation to see results.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!result ? (
          <EmptyState title="No results yet." description="Run a simulation to see which rules match." />
        ) : (
          <>
            {mode === 'delta' && diff ? <RulesTestChangesCard diff={diff} /> : null}

            <RulesTestResultsToolbar
              ruleSearch={ruleSearch}
              setRuleSearch={setRuleSearch}
              showOnlyMatched={showOnlyMatched}
              setShowOnlyMatched={setShowOnlyMatched}
              result={result}
            />

            <RulesTestRulesList
              title="Matched"
              description={`${matchedRules.length} rule(s) matched.`}
              rules={matchedRules}
              filter={filterRuleList}
            />
            <RulesTestRulesList
              title="FOR rules (timers)"
              description={`${scheduledForRules.length} rule(s) would schedule a timer (not satisfied yet).`}
              rules={scheduledForRules}
              filter={filterRuleList}
            />

            <details className="rounded-md border p-3">
              <summary className="cursor-pointer">
                <span className="font-medium">Non-matching rules</span>{' '}
                <span className="text-xs text-muted-foreground">({nonMatchingRules.length})</span>
              </summary>
              <div className="mt-2 space-y-2">
                {filterRuleList(nonMatchingRules).map((r) => (
                  <details key={r.id} className="rounded-md border p-3">
                    <summary className="cursor-pointer">
                      <span className="font-medium">{r.name}</span>{' '}
                      <span className="text-xs text-muted-foreground">({r.kind}, priority {r.priority})</span>
                    </summary>
                    <div className="mt-2 grid gap-3 md:grid-cols-2">
                      <div>
                        <div className="text-xs font-medium text-muted-foreground">Actions (preview)</div>
                        <pre className="mt-1 overflow-auto rounded-md bg-muted p-2 text-xs">
                          {JSON.stringify(r.actions ?? [], null, 2)}
                        </pre>
                      </div>
                      <div>
                        <div className="text-xs font-medium text-muted-foreground">Explain</div>
                        <pre className="mt-1 overflow-auto rounded-md bg-muted p-2 text-xs">
                          {JSON.stringify(r.trace ?? {}, null, 2)}
                        </pre>
                      </div>
                    </div>
                  </details>
                ))}
              </div>
            </details>
          </>
        )}
      </CardContent>
    </Card>
  )
}


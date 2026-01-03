import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { SimulationDiff } from '@/features/rulesTest/utils/computeSimulationDiff'

export function RulesTestChangesCard({ diff }: { diff: SimulationDiff }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Changes</CardTitle>
        <CardDescription>{diff.changedRules.length} rule(s) changed match status compared to baseline.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {diff.changedRules.length === 0 ? (
          <div className="text-sm text-muted-foreground">No rule match changes.</div>
        ) : (
          diff.changedRules.map(({ id, from, to }) => (
            <details key={id} className="rounded-md border p-3">
              <summary className="cursor-pointer">
                <span className="font-medium">{to.name}</span>{' '}
                <span className="text-xs text-muted-foreground">
                  ({to.kind}, priority {to.priority}) • {from.status} → {to.status}
                </span>
              </summary>
              <div className="mt-2 grid gap-3 md:grid-cols-2">
                <div>
                  <div className="text-xs font-medium text-muted-foreground">Baseline</div>
                  <pre className="mt-1 overflow-auto rounded-md bg-muted p-2 text-xs">
                    {JSON.stringify({ status: from.status, actions: from.actions, trace: from.trace }, null, 2)}
                  </pre>
                </div>
                <div>
                  <div className="text-xs font-medium text-muted-foreground">After change</div>
                  <pre className="mt-1 overflow-auto rounded-md bg-muted p-2 text-xs">
                    {JSON.stringify({ status: to.status, actions: to.actions, trace: to.trace }, null, 2)}
                  </pre>
                </div>
              </div>
            </details>
          ))
        )}
      </CardContent>
    </Card>
  )
}


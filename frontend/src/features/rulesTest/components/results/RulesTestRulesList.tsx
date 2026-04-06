import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export type SimulatedRule = {
  id: number
  name: string
  kind: string
  priority: number
  matched?: boolean
  blockedByStopProcessing?: boolean
  blockedByRuleId?: number
  trace?: unknown
  actions?: unknown
  for?: { status?: string; seconds?: number } | null
}

export function RulesTestRulesList({
  title,
  description,
  rules,
  filter,
}: {
  title: string
  description: string
  rules: SimulatedRule[]
  filter: (list: SimulatedRule[]) => SimulatedRule[]
}) {
  const filtered = filter(rules)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {filtered.length === 0 ? (
          <div className="text-sm text-muted-foreground">None.</div>
        ) : (
          filtered.map((r) => (
            <details key={r.id} className="rounded-md border p-3">
              <summary className="cursor-pointer">
                <span className="font-medium">{r.name}</span>{' '}
                <span className="text-xs text-muted-foreground">
                  ({r.kind}, priority {r.priority})
                  {title.startsWith('FOR') && r.for?.seconds ? ` • would schedule ${r.for.seconds}s` : ''}
                </span>
                {r.blockedByStopProcessing && (
                  <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-200">
                    Blocked by rule #{r.blockedByRuleId}
                  </span>
                )}
              </summary>
              <div className="mt-2 grid gap-3 md:grid-cols-2">
                <div>
                  <div className="text-xs font-medium text-muted-foreground">Actions (preview)</div>
                  <pre className="mt-1 overflow-auto rounded-md bg-muted p-2 text-xs">{JSON.stringify(r.actions ?? [], null, 2)}</pre>
                </div>
                <div>
                  <div className="text-xs font-medium text-muted-foreground">Explain</div>
                  <pre className="mt-1 overflow-auto rounded-md bg-muted p-2 text-xs">{JSON.stringify(r.trace ?? {}, null, 2)}</pre>
                </div>
              </div>
            </details>
          ))
        )}
      </CardContent>
    </Card>
  )
}


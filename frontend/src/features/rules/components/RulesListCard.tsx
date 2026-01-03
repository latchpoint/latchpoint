import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Pill } from '@/components/ui/pill'
import type { Rule } from '@/types'

import { countThenActions } from '@/features/rules/builder'

type Props = {
  isLoading: boolean
  rules: Rule[]
  onEdit: (rule: Rule) => void
}

export function RulesListCard({ isLoading, rules, onEdit }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Existing Rules</CardTitle>
        <CardDescription>{isLoading ? 'Loading…' : `${rules.length} rule(s)`}</CardDescription>
      </CardHeader>
      <CardContent>
        {rules.length === 0 ? (
          <EmptyState title="No rules yet." description="Create a rule above to get started." />
        ) : (
          <div className="space-y-2">
            {rules.map((r) => (
              <div
                key={r.id}
                className="flex flex-col gap-2 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div>
                  <div className="font-medium">
                    {r.name} <span className="text-xs text-muted-foreground">({r.kind}, priority {r.priority})</span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className={r.enabled ? 'text-success' : 'text-muted-foreground'}>
                      {r.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                    <span>•</span>
                    <span>Schema v{r.schemaVersion}</span>
                    <span>•</span>
                    <span>Cooldown: {r.cooldownSeconds == null ? '—' : `${r.cooldownSeconds}s`}</span>
                    <span>•</span>
                    <span>Actions: {countThenActions(r.definition)}</span>
                  </div>

                  <div className="mt-2">
                    <div className="text-xs text-muted-foreground">Entities</div>
                    {r.entityIds.length === 0 ? (
                      <div className="text-xs text-muted-foreground">—</div>
                    ) : (
                      <ul className="mt-1 flex flex-wrap gap-1">
                        {r.entityIds.map((id) => (
                          <li key={id}>
                            <Pill>{id}</Pill>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
                <Button type="button" variant="outline" onClick={() => onEdit(r)}>
                  Edit
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}


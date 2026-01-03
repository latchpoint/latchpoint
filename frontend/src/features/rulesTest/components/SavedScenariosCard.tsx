import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import type { SavedScenario } from '@/features/rulesTest/scenarios'

type Props = {
  scenarioName: string
  onScenarioNameChange: (next: string) => void
  onSave: () => void
  savedScenarios: SavedScenario[]
  selectedScenario: string
  onSelectedScenarioChange: (next: string) => void
  onLoad: (name: string) => void
  onDelete: () => void
  disabled?: boolean
}

export function SavedScenariosCard({
  scenarioName,
  onScenarioNameChange,
  onSave,
  savedScenarios,
  selectedScenario,
  onSelectedScenarioChange,
  onLoad,
  onDelete,
  disabled,
}: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Saved scenarios</CardTitle>
        <CardDescription>Stored in your browser (localStorage).</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="space-y-1 md:col-span-2">
            <label className="text-xs text-muted-foreground">Scenario name</label>
            <Input
              value={scenarioName}
              onChange={(e) => onScenarioNameChange(e.target.value)}
              placeholder="e.g., Door opened + motion"
              disabled={disabled}
            />
          </div>
          <div className="flex items-end gap-2">
            <Button type="button" variant="outline" onClick={onSave} disabled={disabled}>
              Save
            </Button>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <div className="space-y-1 md:col-span-2">
            <label className="text-xs text-muted-foreground">
              Load <HelpTip className="ml-1" content="Loads a saved scenario from your browser." />
            </label>
            <Select
              size="sm"
              value={selectedScenario}
              onChange={(e) => {
                const next = e.target.value
                onSelectedScenarioChange(next)
                if (next) onLoad(next)
              }}
              disabled={disabled}
            >
              <option value="">—</option>
              {savedScenarios.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex items-end gap-2">
            <Button type="button" variant="outline" onClick={onDelete} disabled={!selectedScenario || disabled}>
              Delete
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}


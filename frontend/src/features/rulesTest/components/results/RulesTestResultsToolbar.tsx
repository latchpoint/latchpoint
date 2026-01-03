import { Button } from '@/components/ui/button'
import { HelpTip } from '@/components/ui/help-tip'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import type { RuleSimulateResult } from '@/types'

type Props = {
  ruleSearch: string
  setRuleSearch: (next: string) => void
  showOnlyMatched: boolean
  setShowOnlyMatched: (next: boolean) => void
  result: RuleSimulateResult
}

export function RulesTestResultsToolbar({
  ruleSearch,
  setRuleSearch,
  showOnlyMatched,
  setShowOnlyMatched,
  result,
}: Props) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      <div className="space-y-1 md:col-span-2">
        <label className="text-xs text-muted-foreground">Filter rules</label>
        <Input value={ruleSearch} onChange={(e) => setRuleSearch(e.target.value)} placeholder="Search by rule name…" />
      </div>
      <div className="flex items-end gap-2">
        <div className="flex items-center gap-2">
          <Switch checked={showOnlyMatched} onCheckedChange={setShowOnlyMatched} aria-labelledby="show-only-matched-label" />
          <span id="show-only-matched-label" className="text-sm">
            Only matched{' '}
            <HelpTip className="ml-1" content="Filters the lists down to rules that matched in the current result set." />
          </span>
        </div>
        <Button type="button" variant="outline" onClick={() => navigator.clipboard?.writeText(JSON.stringify(result, null, 2))}>
          <span>
            Copy JSON <HelpTip className="ml-1" content="Copies the full raw simulation response to your clipboard (useful for debugging)." />
          </span>
        </Button>
      </div>
    </div>
  )
}


import { Button } from '@/components/ui/button'
import { HelpTip } from '@/components/ui/help-tip'

export type RulesTestMode = 'scenario' | 'delta'

type Props = {
  mode: RulesTestMode
  onModeChange: (next: RulesTestMode) => void
  disabled?: boolean
}

export function RulesTestModeToggle({ mode, onModeChange, disabled }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm text-muted-foreground">
        Mode{' '}
        <HelpTip
          className="ml-1"
          content="Scenario overrides multiple entity states at once. Single Change compares baseline vs baseline + one state change."
        />
      </span>
      <Button
        type="button"
        size="sm"
        variant={mode === 'scenario' ? 'secondary' : 'outline'}
        onClick={() => onModeChange('scenario')}
        disabled={disabled}
      >
        Scenario
      </Button>
      <Button
        type="button"
        size="sm"
        variant={mode === 'delta' ? 'secondary' : 'outline'}
        onClick={() => onModeChange('delta')}
        disabled={disabled}
      >
        Single Change
      </Button>
    </div>
  )
}


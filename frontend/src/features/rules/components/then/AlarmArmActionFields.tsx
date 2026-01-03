import type { AlarmArmMode } from '@/lib/typeGuards'
import { isAlarmArmMode } from '@/lib/typeGuards'
import { getSelectValue } from '@/lib/formHelpers'
import { HelpTip } from '@/components/ui/help-tip'
import { Select } from '@/components/ui/select'

type Props = {
  mode: AlarmArmMode
  onChangeMode: (next: AlarmArmMode) => void
}

export function AlarmArmActionFields({ mode, onChangeMode }: Props) {
  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground">
        Mode <HelpTip className="ml-1" content="Which armed mode to switch the alarm into." />
      </label>
      <Select size="sm" value={mode} onChange={(e) => onChangeMode(getSelectValue(e, isAlarmArmMode, 'armed_away'))}>
        <option value="armed_away">Armed away</option>
        <option value="armed_home">Armed home</option>
        <option value="armed_night">Armed night</option>
        <option value="armed_vacation">Armed vacation</option>
      </Select>
    </div>
  )
}


import type { AlarmStateType } from '@/lib/constants'
import { AlarmStateLabels } from '@/lib/constants'
import { Checkbox } from '@/components/ui/checkbox'
import { HelpTip } from '@/components/ui/help-tip'

type Props = {
  title?: string
  helpTip?: string
  states: AlarmStateType[]
  value: AlarmStateType[]
  onChange: (next: AlarmStateType[]) => void
  disabled?: boolean
}

export function AllowedArmStatesPicker({
  title = 'Allowed Arm States',
  helpTip,
  states,
  value,
  onChange,
  disabled,
}: Props) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <div className="text-sm font-medium">{title}</div>
        {helpTip ? <HelpTip content={helpTip} /> : null}
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        {states.map((state) => (
          <label key={state} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={value.includes(state)}
              onChange={(e) => {
                const next = new Set(value)
                if (e.target.checked) next.add(state)
                else next.delete(state)
                onChange(Array.from(next))
              }}
              disabled={disabled}
            />
            {AlarmStateLabels[state]}
          </label>
        ))}
      </div>
    </div>
  )
}


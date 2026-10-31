import { DateTimeRangePicker, type DateTimeRangeValue } from '@/components/ui/date-time-range-picker'
import { HelpTip } from '@/components/ui/help-tip'

type Props = {
  label?: string
  value: DateTimeRangeValue
  onChange: (next: DateTimeRangeValue) => void
  disabled?: boolean
  helpTipContent?: string
  caption?: string
  showHelper?: boolean
  /** Whether the picker offers Clear. Off for a window that has to keep its end. */
  clearable?: boolean
}

export function ActiveWindowPicker({
  label = 'Active window (optional)',
  value,
  onChange,
  disabled,
  helpTipContent = "If set, the code only works between these timestamps (in the user's local timezone). Leave blank for no overall date range.",
  caption = 'Optional overall validity window.',
  showHelper = true,
  clearable = true,
}: Props) {
  return (
    <div>
      <DateTimeRangePicker label={label} value={value} onChange={onChange} disabled={disabled} clearable={clearable} />
      {showHelper && (
        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          <HelpTip content={helpTipContent} />
          <span>{caption}</span>
        </div>
      )}
    </div>
  )
}

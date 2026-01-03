import type { ReactNode } from 'react'

import { Checkbox } from '@/components/ui/checkbox'
import { DAY_LABELS, daysSetToMask, formatDaysMask } from '@/features/codes/utils/daysOfWeek'

type Props = {
  title?: string
  header?: ReactNode
  value: Set<number>
  onChange: (next: Set<number>) => void
  disabled?: boolean
  summaryClassName?: string
}

export function DaysOfWeekPicker({
  title = 'Days of week',
  header,
  value,
  onChange,
  disabled,
  summaryClassName = 'text-xs text-muted-foreground',
}: Props) {
  return (
    <div className="space-y-2">
      {header ? <div>{header}</div> : <div className="text-sm font-medium">{title}</div>}
      <div className="flex flex-wrap gap-2">
        {DAY_LABELS.map((label, idx) => (
          <label key={label} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={value.has(idx)}
              onChange={(e) => {
                const next = new Set(value)
                if (e.target.checked) next.add(idx)
                else next.delete(idx)
                onChange(next)
              }}
              disabled={disabled}
            />
            {label}
          </label>
        ))}
      </div>
      <div className={summaryClassName}>{formatDaysMask(daysSetToMask(value))}</div>
    </div>
  )
}

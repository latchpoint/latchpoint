import {
  addDays,
  addMonths,
  endOfMonth,
  endOfWeek,
  format,
  isAfter,
  isSameDay,
  isWithinInterval,
  startOfMonth,
  startOfWeek,
  subMonths,
} from 'date-fns'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { DateTimeRangeValue } from '@/components/ui/date-time-range-picker'
import { getTimePart, parseLocalDateTime, withTimePreserveDate } from '@/components/ui/date-time-range-picker.utils'

type Props = {
  value: DateTimeRangeValue
  onChange: (value: DateTimeRangeValue) => void
  disabled: boolean
  month: Date
  setMonth: (updater: (prev: Date) => Date) => void
  onPickDay: (day: Date) => void
  startDate: Date | null
  endDate: Date | null
  onClose: () => void
}

export function DateTimeRangePickerPopover({
  value,
  onChange,
  disabled,
  month,
  setMonth,
  onPickDay,
  startDate,
  endDate,
  onClose,
}: Props) {
  const calendarDays = (() => {
    const start = startOfWeek(startOfMonth(month))
    const end = endOfWeek(endOfMonth(month))
    const days: Date[] = []
    for (let d = start; !isAfter(d, end); d = addDays(d, 1)) {
      days.push(d)
    }
    return days
  })()

  const isInRange = (day: Date): boolean => {
    if (!startDate || !endDate) return false
    const start = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate())
    const end = new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate())
    return isWithinInterval(day, { start, end })
  }

  const isRangeStart = (day: Date): boolean => !!startDate && isSameDay(day, startDate)
  const isRangeEnd = (day: Date): boolean => !!endDate && isSameDay(day, endDate)

  const clear = () => onChange({ start: '', end: '' })

  const canEditStartTime = Boolean(parseLocalDateTime(value.start))
  const canEditEndTime = Boolean(parseLocalDateTime(value.end))

  return (
    <div className="absolute z-50 mt-2 w-full rounded-md border bg-popover p-3 shadow-md">
      <div className="mb-2 flex items-center justify-between gap-2">
        <Button type="button" variant="secondary" onClick={() => setMonth((m) => subMonths(m, 1))}>
          Prev
        </Button>
        <div className="text-sm font-medium">{format(month, 'MMMM yyyy')}</div>
        <Button type="button" variant="secondary" onClick={() => setMonth((m) => addMonths(m, 1))}>
          Next
        </Button>
      </div>

      <div className="grid grid-cols-7 gap-1 text-center text-xs text-muted-foreground">
        {['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map((d) => (
          <div key={d} className="py-1">
            {d}
          </div>
        ))}
      </div>

      <div className="mt-1 grid grid-cols-7 gap-1">
        {calendarDays.map((day) => {
          const muted = day.getMonth() !== month.getMonth()
          const selected = isRangeStart(day) || isRangeEnd(day)
          const inRange = isInRange(day)
          return (
            <button
              key={day.toISOString()}
              type="button"
              className={cn(
                'h-9 rounded-md border border-transparent text-sm',
                muted && 'text-muted-foreground',
                inRange && 'bg-primary/10',
                selected && 'bg-primary text-primary-foreground',
                !disabled && 'hover:border-input hover:bg-muted'
              )}
              onClick={() => onPickDay(day)}
              disabled={disabled}
            >
              {format(day, 'd')}
            </button>
          )
        })}
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="space-y-2">
          <div className="text-sm font-medium">From</div>
          <Input
            type="time"
            value={getTimePart(value.start, '00:00')}
            onChange={(e) => onChange({ start: withTimePreserveDate(value.start, e.target.value), end: value.end })}
            disabled={disabled || !canEditStartTime}
          />
        </div>
        <div className="space-y-2">
          <div className="text-sm font-medium">Until</div>
          <Input
            type="time"
            value={getTimePart(value.end, '00:00')}
            onChange={(e) => onChange({ start: value.start, end: withTimePreserveDate(value.end, e.target.value) })}
            disabled={disabled || !canEditEndTime}
          />
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between gap-2">
        <Button type="button" variant="secondary" onClick={clear} disabled={disabled}>
          Clear
        </Button>
        <Button type="button" onClick={onClose} disabled={disabled}>
          Done
        </Button>
      </div>
    </div>
  )
}


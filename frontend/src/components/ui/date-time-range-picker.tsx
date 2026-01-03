import { useEffect, useMemo, useRef, useState } from 'react'
import {
  format,
  isBefore,
} from 'date-fns'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { DateTimeRangePickerPopover } from '@/components/ui/date-time-range-picker/DateTimeRangePickerPopover'
import { parseLocalDateTime, withDatePreserveTime } from '@/components/ui/date-time-range-picker.utils'

export type DateTimeRangeValue = {
  start: string
  end: string
}

type DateTimeRangePickerProps = {
  label?: string
  value: DateTimeRangeValue
  onChange: (value: DateTimeRangeValue) => void
  disabled?: boolean
}

export function DateTimeRangePicker({
  label = 'Active window',
  value,
  onChange,
  disabled = false,
}: DateTimeRangePickerProps) {
  const [open, setOpen] = useState(false)
  const popoverRef = useRef<HTMLDivElement | null>(null)

  const startDate = useMemo(() => parseLocalDateTime(value.start), [value.start])
  const endDate = useMemo(() => parseLocalDateTime(value.end), [value.end])

  const [month, setMonth] = useState<Date>(() => startDate || endDate || new Date())

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!open) return
      const target = event.target as Node | null
      if (!target) return
      if (popoverRef.current && !popoverRef.current.contains(target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  const displayValue = useMemo(() => {
    if (!startDate && !endDate) return 'Select date range…'
    if (startDate && !endDate) return `${format(startDate, 'PP p')} → …`
    if (!startDate && endDate) return `… → ${format(endDate, 'PP p')}`
    return `${format(startDate!, 'PP p')} → ${format(endDate!, 'PP p')}`
  }, [startDate, endDate])

  const onPickDay = (day: Date) => {
    if (disabled) return
    const existingStart = value.start
    const existingEnd = value.end
    const existingStartDate = parseLocalDateTime(existingStart)
    const existingEndDate = parseLocalDateTime(existingEnd)

    if (!existingStartDate || (existingStartDate && existingEndDate)) {
      onChange({
        start: withDatePreserveTime(existingStart, day, '00:00'),
        end: '',
      })
      return
    }

    if (isBefore(day, existingStartDate)) {
      onChange({
        start: withDatePreserveTime(existingStart, day, '00:00'),
        end: withDatePreserveTime(existingEnd, existingStartDate, '00:00'),
      })
      return
    }

    onChange({
      start: existingStart,
      end: withDatePreserveTime(existingEnd, day, '00:00'),
    })
  }

  return (
    <div className="space-y-2">
      <div className="text-sm font-medium">{label}</div>

      <div className="relative" ref={popoverRef}>
        <Button
          type="button"
          variant="secondary"
          className="w-full justify-between"
          onClick={() => setOpen((v) => !v)}
          disabled={disabled}
        >
          <span className={cn('truncate', !startDate && !endDate && 'text-muted-foreground')}>
            {displayValue}
          </span>
          <span className="text-muted-foreground">▾</span>
        </Button>

        {open && (
          <DateTimeRangePickerPopover
            value={value}
            onChange={onChange}
            disabled={disabled}
            month={month}
            setMonth={setMonth}
            onPickDay={onPickDay}
            startDate={startDate}
            endDate={endDate}
            onClose={() => setOpen(false)}
          />
        )}
      </div>
    </div>
  )
}

export default DateTimeRangePicker

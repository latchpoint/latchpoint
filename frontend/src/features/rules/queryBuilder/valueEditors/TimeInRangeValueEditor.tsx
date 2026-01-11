/**
 * Custom value editor for time_in_range condition
 * Provides start/end time inputs + day-of-week picker + timezone selector
 */
import { useMemo } from 'react'
import type { ValueEditorProps } from 'react-querybuilder'
import type { TimeInRangeValue } from '../types'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { cn } from '@/lib/utils'

const ALL_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const
const DAY_LABELS: Record<(typeof ALL_DAYS)[number], string> = {
  mon: 'Mon',
  tue: 'Tue',
  wed: 'Wed',
  thu: 'Thu',
  fri: 'Fri',
  sat: 'Sat',
  sun: 'Sun',
}

export function TimeInRangeValueEditor({ value, handleOnChange, disabled }: ValueEditorProps) {
  const currentValue = (value as TimeInRangeValue) || {
    start: '22:00',
    end: '06:00',
    days: [...ALL_DAYS],
    tz: 'system',
  }

  const selectedDays = useMemo(() => new Set((currentValue.days || []).map((d) => d.toLowerCase())), [currentValue.days])
  const tzMode = (currentValue.tz || 'system') === 'system' ? 'system' : 'custom'

  const updateValue = (updates: Partial<TimeInRangeValue>) => {
    handleOnChange({ ...currentValue, ...updates } as TimeInRangeValue)
  }

  const toggleDay = (day: (typeof ALL_DAYS)[number]) => {
    const next = new Set(selectedDays)
    if (next.has(day)) next.delete(day)
    else next.add(day)
    updateValue({ days: Array.from(next) })
  }

  const setTzMode = (mode: 'system' | 'custom') => {
    if (mode === 'system') updateValue({ tz: 'system' })
    else updateValue({ tz: currentValue.tz && currentValue.tz !== 'system' ? currentValue.tz : 'UTC' })
  }

  return (
    <div className="space-y-3 rounded-md border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs font-medium text-muted-foreground">Start</label>
        <Input
          type="time"
          value={currentValue.start}
          onChange={(e) => updateValue({ start: e.target.value })}
          disabled={disabled}
          className="h-8 w-[120px]"
        />
        <label className="text-xs font-medium text-muted-foreground">End</label>
        <Input
          type="time"
          value={currentValue.end}
          onChange={(e) => updateValue({ end: e.target.value })}
          disabled={disabled}
          className="h-8 w-[120px]"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">Days</label>
        <div className="flex flex-wrap gap-1.5">
          {ALL_DAYS.map((day) => (
            <button
              key={day}
              type="button"
              disabled={disabled}
              onClick={() => toggleDay(day)}
              className={cn(
                'rounded-md px-2 py-1 text-xs font-medium transition-colors',
                'border',
                selectedDays.has(day)
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-input bg-background hover:bg-accent hover:text-accent-foreground',
                disabled && 'cursor-not-allowed opacity-50'
              )}
            >
              {DAY_LABELS[day]}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">Time zone</label>
          <Select
            value={tzMode}
            onChange={(e) => setTzMode(e.target.value as 'system' | 'custom')}
            disabled={disabled}
            size="sm"
          >
            <option value="system">System time zone</option>
            <option value="custom">Choose time zone…</option>
          </Select>
        </div>

        {tzMode === 'custom' && (
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">IANA ID</label>
            <Input
              type="text"
              value={currentValue.tz}
              onChange={(e) => updateValue({ tz: e.target.value })}
              disabled={disabled}
              placeholder="e.g. America/New_York"
              className="h-8"
            />
          </div>
        )}
      </div>
    </div>
  )
}


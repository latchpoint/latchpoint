import { HelpTip } from '@/components/ui/help-tip'
import { ActiveWindowPicker } from '@/features/codes/components/ActiveWindowPicker'
import { DaysOfWeekPicker } from '@/features/codes/components/DaysOfWeekPicker'
import { TimeWindowFields } from '@/features/codes/components/TimeWindowFields'

type Props = {
  disabled: boolean
  startAtLocal: string
  endAtLocal: string
  onActiveWindowChange: (next: { start: string; end: string }) => void
  days: Set<number>
  onDaysChange: (next: Set<number>) => void
  windowStart: string
  windowEnd: string
  onWindowStartChange: (next: string) => void
  onWindowEndChange: (next: string) => void
}

export function CodeTemporaryRestrictionsFields({
  disabled,
  startAtLocal,
  endAtLocal,
  onActiveWindowChange,
  days,
  onDaysChange,
  windowStart,
  windowEnd,
  onWindowStartChange,
  onWindowEndChange,
}: Props) {
  return (
    <>
      <div className="mt-4">
        <ActiveWindowPicker value={{ start: startAtLocal, end: endAtLocal }} onChange={onActiveWindowChange} disabled={disabled} />
      </div>

      <div className="mt-4 space-y-4">
        <DaysOfWeekPicker
          header={
            <div className="flex items-center gap-2">
              <div className="text-sm font-medium">Days allowed</div>
              <HelpTip content="Restrict which weekdays this code can be used. Mon=0…Sun=6." />
            </div>
          }
          value={days}
          onChange={onDaysChange}
          disabled={disabled}
        />

        <TimeWindowFields
          startId="create-window-start"
          endId="create-window-end"
          startValue={windowStart}
          endValue={windowEnd}
          onStartChange={onWindowStartChange}
          onEndChange={onWindowEndChange}
          disabled={disabled}
        />
      </div>
    </>
  )
}


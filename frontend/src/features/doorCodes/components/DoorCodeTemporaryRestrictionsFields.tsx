import { HelpTip } from '@/components/ui/help-tip'
import { ActiveWindowPicker } from '@/features/codes/components/ActiveWindowPicker'
import { DaysOfWeekPicker } from '@/features/codes/components/DaysOfWeekPicker'
import { TimeWindowFields } from '@/features/codes/components/TimeWindowFields'

type Props = {
  disabled: boolean
  activeWindow: { start: string; end: string }
  onActiveWindowChange: (next: { start: string; end: string }) => void
  days: Set<number>
  onDaysChange: (next: Set<number>) => void
  timeWindow: { start: string; end: string }
  onTimeWindowStartChange: (next: string) => void
  onTimeWindowEndChange: (next: string) => void
  startId: string
  endId: string
  showActiveWindowHelper?: boolean
  showTimeWindowHelp?: boolean
}

export function DoorCodeTemporaryRestrictionsFields({
  disabled,
  activeWindow,
  onActiveWindowChange,
  days,
  onDaysChange,
  timeWindow,
  onTimeWindowStartChange,
  onTimeWindowEndChange,
  startId,
  endId,
  showActiveWindowHelper = true,
  showTimeWindowHelp = true,
}: Props) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <div className="text-sm font-medium">Active date range (optional)</div>
          <HelpTip content="If set, the code is only valid between these timestamps." />
        </div>
        <ActiveWindowPicker value={activeWindow} onChange={onActiveWindowChange} disabled={disabled} showHelper={showActiveWindowHelper} />
      </div>

      <DaysOfWeekPicker
        header={
          <div className="flex items-center gap-2">
            <div className="text-sm font-medium">Days of week</div>
            <HelpTip content="Select which days this code is allowed." />
          </div>
        }
        value={days}
        onChange={onDaysChange}
        disabled={disabled}
      />

      <TimeWindowFields
        startId={startId}
        endId={endId}
        startValue={timeWindow.start}
        endValue={timeWindow.end}
        onStartChange={onTimeWindowStartChange}
        onEndChange={onTimeWindowEndChange}
        disabled={disabled}
        showHelp={showTimeWindowHelp}
      />
    </div>
  )
}


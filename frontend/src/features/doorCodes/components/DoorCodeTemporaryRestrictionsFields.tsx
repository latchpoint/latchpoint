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
  /** Defaults to `disabled`. A synced code can have its window editable while the schedule isn't. */
  activeWindowDisabled?: boolean
  /** Hide the days and time window, for a code with dates but no schedule of its own. */
  showSchedule?: boolean
  /** The window can't be cleared, ie a synced code's has to keep its end (#189). */
  activeWindowRequired?: boolean
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
  activeWindowDisabled = disabled,
  showSchedule = true,
  activeWindowRequired = false,
}: Props) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <div className="text-sm font-medium">
            {activeWindowRequired ? 'Active date range' : 'Active date range (optional)'}
          </div>
          <HelpTip
            content={
              activeWindowRequired
                ? 'The code is only valid between these timestamps. The end can be moved but not cleared.'
                : 'If set, the code is only valid between these timestamps.'
            }
          />
        </div>
        <ActiveWindowPicker
          label={activeWindowRequired ? 'Active window' : undefined}
          value={activeWindow}
          onChange={onActiveWindowChange}
          disabled={activeWindowDisabled}
          showHelper={showActiveWindowHelper}
          clearable={!activeWindowRequired}
        />
      </div>

      {showSchedule ? (
        <>
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
        </>
      ) : null}
    </div>
  )
}


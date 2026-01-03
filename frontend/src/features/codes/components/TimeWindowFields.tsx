import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'

type Props = {
  startId: string
  endId: string
  startLabel?: string
  endLabel?: string
  startHelp?: string
  endHelp?: string
  showHelp?: boolean
  startValue: string
  endValue: string
  onStartChange: (next: string) => void
  onEndChange: (next: string) => void
  disabled?: boolean
}

export function TimeWindowFields({
  startId,
  endId,
  startLabel = 'Time window start (optional)',
  endLabel = 'Time window end (optional)',
  startHelp = 'Leave both start and end blank for no daily time restriction.',
  endHelp = 'End must be after start (same-day window). Leave both blank for no daily time restriction.',
  showHelp = true,
  startValue,
  endValue,
  onStartChange,
  onEndChange,
  disabled,
}: Props) {
  const startHelpToUse = showHelp ? startHelp : undefined
  const endHelpToUse = showHelp ? endHelp : undefined

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <FormField label={startLabel} htmlFor={startId} help={startHelpToUse}>
        <Input
          id={startId}
          type="time"
          value={startValue}
          onChange={(e) => onStartChange(e.target.value)}
          disabled={disabled}
        />
      </FormField>
      <FormField label={endLabel} htmlFor={endId} help={endHelpToUse}>
        <Input
          id={endId}
          type="time"
          value={endValue}
          onChange={(e) => onEndChange(e.target.value)}
          disabled={disabled}
        />
      </FormField>
    </div>
  )
}

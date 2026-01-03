import { Button } from '@/components/ui/button'
import { DateTimeRangePicker } from '@/components/ui/date-time-range-picker'
import { FormField } from '@/components/ui/form-field'
import { SectionCard } from '@/components/ui/section-card'
import { Select } from '@/components/ui/select'
import { eventTypeOptions } from '@/features/events/constants/eventPresentation'

type Props = {
  eventType: string
  setEventType: (next: string) => void
  range: { start: string; end: string }
  setRange: (next: { start: string; end: string }) => void
  onRefresh: () => void
  onClear: () => void
  isLoading: boolean
}

export function EventsFiltersCard({
  eventType,
  setEventType,
  range,
  setRange,
  onRefresh,
  onClear,
  isLoading,
}: Props) {
  return (
    <SectionCard
      title="Filters"
      description="Narrow down event history by type and time window."
      actions={
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onRefresh} disabled={isLoading}>
            Refresh
          </Button>
          <Button type="button" variant="secondary" onClick={onClear} disabled={isLoading}>
            Clear
          </Button>
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-2">
        <FormField label="Event type" htmlFor="event-type">
          <Select id="event-type" value={eventType} onChange={(e) => setEventType(e.target.value)}>
            {eventTypeOptions.map((opt) => (
              <option key={opt.value || 'all'} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </Select>
        </FormField>
        <DateTimeRangePicker label="Time window" value={range} onChange={setRange} />
      </div>
    </SectionCard>
  )
}


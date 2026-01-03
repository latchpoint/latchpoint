import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { LoadingInline } from '@/components/ui/loading-inline'
import { SectionCard } from '@/components/ui/section-card'
import type { AlarmEvent } from '@/types'
import { EventRow } from '@/features/events/components/EventRow'

type Props = {
  events: AlarmEvent[]
  total: number
  page: number
  totalPages: number
  hasNext: boolean
  hasPrevious: boolean
  error: string | null
  isLoading: boolean
  isFetching: boolean
  onNextPage: () => void
  onPreviousPage: () => void
}

export function EventsHistoryCard({
  events,
  total,
  page,
  totalPages,
  hasNext,
  hasPrevious,
  error,
  isLoading,
  isFetching,
  onNextPage,
  onPreviousPage,
}: Props) {
  return (
    <SectionCard title="Event history" description={total ? `${total} total` : 'Most recent events first.'}>
      {error ? (
        <Alert variant="error">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {isLoading ? (
        <div className="py-6">
          <LoadingInline label="Loading events…" />
        </div>
      ) : events.length === 0 ? (
        <EmptyState title="No events" description="Try widening the time window or clearing filters." />
      ) : (
        <div className="space-y-1">
          {events.map((event) => (
            <EventRow key={event.id} event={event} />
          ))}
        </div>
      )}

      {totalPages > 1 ? (
        <div className="mt-3 flex items-center justify-between gap-2">
          <div className="text-xs text-muted-foreground">
            Page {page} of {totalPages}
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onPreviousPage}
              disabled={!hasPrevious || isFetching}
            >
              Prev
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onNextPage}
              disabled={!hasNext || isFetching}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </SectionCard>
  )
}


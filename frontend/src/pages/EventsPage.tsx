import { Page } from '@/components/layout'
import { EventsFiltersCard } from '@/features/events/components/EventsFiltersCard'
import { EventsHistoryCard } from '@/features/events/components/EventsHistoryCard'
import { useEventsPageModel } from '@/features/events/hooks/useEventsPageModel'

export function EventsPage() {
  const model = useEventsPageModel()

  return (
    <Page title="Events">
      <EventsFiltersCard
        eventType={model.eventType}
        setEventType={model.setEventType}
        range={model.range}
        setRange={model.setRange}
        onRefresh={() => model.eventsQuery.refetch()}
        onClear={model.clearFilters}
        isLoading={model.isLoading}
      />

      <EventsHistoryCard
        events={model.events}
        total={model.total}
        page={model.page}
        totalPages={model.totalPages}
        hasNext={model.hasNext}
        hasPrevious={model.hasPrevious}
        error={model.error}
        isLoading={model.isLoading}
        isFetching={model.isFetching}
        onNextPage={model.goToNextPage}
        onPreviousPage={model.goToPreviousPage}
      />
    </Page>
  )
}

export default EventsPage

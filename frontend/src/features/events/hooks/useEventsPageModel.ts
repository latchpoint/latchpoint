import { useMemo, useState } from 'react'
import { useEventsPaginatedQuery } from '@/hooks/useEventsQueries'
import type { EventTypeType } from '@/lib/constants'
import { toUtcIsoFromDatetimeLocal } from '@/features/events/utils/dateTime'

const PAGE_SIZE = 10

export function useEventsPageModel() {
  const [eventType, setEventType] = useState<string>('')
  const [range, setRange] = useState<{ start: string; end: string }>({ start: '', end: '' })
  const [page, setPage] = useState(1)

  const filters = useMemo(() => {
    const startDate = toUtcIsoFromDatetimeLocal(range.start)
    const endDate = toUtcIsoFromDatetimeLocal(range.end)
    return {
      eventType: (eventType || undefined) as EventTypeType | undefined,
      startDate: startDate || undefined,
      endDate: endDate || undefined,
    }
  }, [eventType, range.end, range.start])

  const eventsQuery = useEventsPaginatedQuery(filters, page, PAGE_SIZE)

  const events = eventsQuery.data?.data ?? []
  const total = eventsQuery.data?.total ?? 0
  const totalPages = eventsQuery.data?.totalPages ?? 1
  const hasNext = eventsQuery.data?.hasNext ?? false
  const hasPrevious = eventsQuery.data?.hasPrevious ?? false

  const isLoading = eventsQuery.isLoading
  const isFetching = eventsQuery.isFetching
  const error = (eventsQuery.error as { message?: string } | null)?.message || null

  const clearFilters = () => {
    setEventType('')
    setRange({ start: '', end: '' })
    setPage(1)
  }

  const goToNextPage = () => {
    if (hasNext) setPage((p) => p + 1)
  }

  const goToPreviousPage = () => {
    if (hasPrevious) setPage((p) => p - 1)
  }

  return {
    eventType,
    setEventType: (value: string) => {
      setEventType(value)
      setPage(1)
    },
    range,
    setRange: (value: { start: string; end: string }) => {
      setRange(value)
      setPage(1)
    },
    filters,
    eventsQuery,
    events,
    total,
    page,
    totalPages,
    hasNext,
    hasPrevious,
    isLoading,
    isFetching,
    error,
    clearFilters,
    goToNextPage,
    goToPreviousPage,
  }
}


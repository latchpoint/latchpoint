import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import type { EventTypeType } from '@/lib/constants'
import { alarmService } from '@/services'
import { queryKeys } from '@/types'
import { useAuthSessionQuery } from '@/hooks/useAuthQueries'

export type EventsQueryFilters = {
  eventType?: EventTypeType
  startDate?: string
  endDate?: string
  userId?: string
}

export function useEventsInfiniteQuery(filters: EventsQueryFilters, pageSize: number = 50) {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false

  const key = [
    ...queryKeys.events.all,
    'infinite',
    filters.eventType || null,
    filters.startDate || null,
    filters.endDate || null,
    filters.userId || null,
    pageSize,
  ] as const

  return useInfiniteQuery({
    queryKey: key,
    enabled: isAuthenticated,
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      alarmService.getEvents({
        page: pageParam as number,
        pageSize,
        ordering: '-timestamp',
        eventType: filters.eventType,
        startDate: filters.startDate,
        endDate: filters.endDate,
        userId: filters.userId,
      }),
    getNextPageParam: (lastPage) => (lastPage.hasNext ? lastPage.page + 1 : undefined),
  })
}

export function useEventsPaginatedQuery(filters: EventsQueryFilters, page: number, pageSize: number = 20) {
  const session = useAuthSessionQuery()
  const isAuthenticated = session.data?.isAuthenticated ?? false

  const key = [
    ...queryKeys.events.all,
    'paginated',
    filters.eventType || null,
    filters.startDate || null,
    filters.endDate || null,
    filters.userId || null,
    page,
    pageSize,
  ] as const

  return useQuery({
    queryKey: key,
    enabled: isAuthenticated,
    queryFn: () =>
      alarmService.getEvents({
        page,
        pageSize,
        ordering: '-timestamp',
        eventType: filters.eventType,
        startDate: filters.startDate,
        endDate: filters.endDate,
        userId: filters.userId,
      }),
  })
}

export default useEventsInfiniteQuery


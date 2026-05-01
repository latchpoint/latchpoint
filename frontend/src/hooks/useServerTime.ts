import { useQuery } from '@tanstack/react-query'

import { systemService } from '@/services'
import { queryKeys } from '@/types'

export function useServerTimeQuery() {
  return useQuery({
    queryKey: queryKeys.system.time,
    queryFn: systemService.time,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    staleTime: 30_000,
    retry: 1,
  })
}

export default useServerTimeQuery

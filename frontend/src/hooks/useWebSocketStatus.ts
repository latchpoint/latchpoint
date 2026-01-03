import { useQuery } from '@tanstack/react-query'
import type { WebSocketStatus } from '@/types'
import { queryKeys } from '@/types'

export function useWebSocketStatus() {
  return useQuery<WebSocketStatus>({
    queryKey: queryKeys.websocket.status,
    queryFn: async () => 'disconnected' as WebSocketStatus,
    initialData: 'disconnected',
    enabled: false,
  })
}

export default useWebSocketStatus


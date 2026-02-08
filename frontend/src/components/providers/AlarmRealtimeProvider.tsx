import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { wsManager } from '@/services'
import type { AlarmEvent, AlarmWebSocketMessage, WebSocketStatus, Entity } from '@/types'
import { queryKeys } from '@/types'
import { useAuthSessionQuery } from '@/hooks/useAuthQueries'
import { isAlarmStatePayload, isAlarmEventPayload, isCountdownPayload, isSystemStatusPayload, isEntitySyncPayload } from '@/lib/typeGuards'
import { DEFAULT_RECENT_EVENTS_LIMIT } from '@/lib/constants'

let unsubscribeMessages: (() => void) | null = null
let unsubscribeStatus: (() => void) | null = null

function upsertRecentEvent(prev: AlarmEvent[] | undefined, nextEvent: AlarmEvent): AlarmEvent[] {
  const existing = Array.isArray(prev) ? prev : []
  const without = existing.filter((e) => e.id !== nextEvent.id)
  return [nextEvent, ...without].slice(0, DEFAULT_RECENT_EVENTS_LIMIT)
}

export function AlarmRealtimeProvider() {
  const queryClient = useQueryClient()
  const sessionQuery = useAuthSessionQuery()
  const isAuthenticated = sessionQuery.data.isAuthenticated
  const cleanupTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    // Cancel any pending cleanup from StrictMode unmount
    if (cleanupTimeoutRef.current) {
      clearTimeout(cleanupTimeoutRef.current)
      cleanupTimeoutRef.current = null
    }

    if (!isAuthenticated) {
      wsManager.disconnect()
      queryClient.setQueryData(queryKeys.websocket.status, 'disconnected' as WebSocketStatus)
      if (unsubscribeMessages) {
        unsubscribeMessages()
        unsubscribeMessages = null
      }
      if (unsubscribeStatus) {
        unsubscribeStatus()
        unsubscribeStatus = null
      }
      queryClient.setQueryData(queryKeys.alarm.countdown, null)
      return
    }

    if (!unsubscribeStatus) {
      unsubscribeStatus = wsManager.onStatusChange((status) => {
        queryClient.setQueryData(queryKeys.websocket.status, status)
        if (status === 'connected') {
          void queryClient.invalidateQueries({ queryKey: queryKeys.alarm.state })
          // After a backend restart, the first websocket snapshot can arrive before integrations
          // finish reconnecting; force a one-time status refresh on reconnect.
          void queryClient.invalidateQueries({ queryKey: queryKeys.homeAssistant.status })
          void queryClient.invalidateQueries({ queryKey: queryKeys.mqtt.status })
          void queryClient.invalidateQueries({ queryKey: queryKeys.zwavejs.status })
          void queryClient.invalidateQueries({ queryKey: queryKeys.zigbee2mqtt.status })
          void queryClient.invalidateQueries({ queryKey: queryKeys.frigate.status })
        }
      })
    }

    if (!unsubscribeMessages) {
      unsubscribeMessages = wsManager.onMessage((message: AlarmWebSocketMessage) => {
        switch (message.type) {
          case 'alarm_state': {
            // Discriminated union narrows payload type, but validate at runtime for safety
            if (!isAlarmStatePayload(message.payload)) {
              console.error('Invalid alarm_state payload', message.payload)
              break
            }
            queryClient.setQueryData(queryKeys.alarm.state, message.payload.state)
            break
          }
          case 'event': {
            if (!isAlarmEventPayload(message.payload)) {
              console.error('Invalid event payload', message.payload)
              break
            }
            queryClient.setQueryData(queryKeys.events.recent, (prev) =>
              upsertRecentEvent(prev as AlarmEvent[] | undefined, message.payload.event)
            )
            break
          }
          case 'countdown': {
            if (!isCountdownPayload(message.payload)) {
              console.error('Invalid countdown payload', message.payload)
              break
            }
            queryClient.setQueryData(queryKeys.alarm.countdown, message.payload)
            break
          }
          case 'health':
            // Health messages received but not processed yet
            break
          case 'system_status': {
            if (!isSystemStatusPayload(message.payload)) {
              console.error('Invalid system_status payload', message.payload)
              break
            }
            queryClient.setQueryData(queryKeys.homeAssistant.status, message.payload.homeAssistant)
            queryClient.setQueryData(queryKeys.mqtt.status, message.payload.mqtt)
            queryClient.setQueryData(queryKeys.zwavejs.status, message.payload.zwavejs)
            queryClient.setQueryData(queryKeys.zigbee2mqtt.status, message.payload.zigbee2mqtt)
            queryClient.setQueryData(queryKeys.frigate.status, message.payload.frigate)
            break
          }
          case 'entity_sync': {
            if (!isEntitySyncPayload(message.payload)) {
              console.error('Invalid entity_sync payload', message.payload)
              break
            }
            queryClient.setQueryData<Entity[]>(queryKeys.entities.all, (prev) => {
              if (!prev) return prev
              const changed = new Map(
                message.payload.entities.map((e) => [e.entityId, e.newState])
              )
              return prev.map((entity) => {
                const newState = changed.get(entity.entityId)
                if (newState !== undefined) {
                  return { ...entity, lastState: newState }
                }
                return entity
              })
            })
            break
          }
        }
      })
    }

    wsManager.connect()

    return () => {
      // Delay cleanup to handle React StrictMode double-invoke
      // If component remounts quickly, the cleanup will be cancelled
      cleanupTimeoutRef.current = setTimeout(() => {
        wsManager.disconnect()
        queryClient.setQueryData(queryKeys.websocket.status, 'disconnected' as WebSocketStatus)
        if (unsubscribeMessages) {
          unsubscribeMessages()
          unsubscribeMessages = null
        }
        if (unsubscribeStatus) {
          unsubscribeStatus()
          unsubscribeStatus = null
        }
        queryClient.setQueryData(queryKeys.alarm.countdown, null)
      }, 100)
    }
  }, [isAuthenticated, queryClient])

  return null
}

export default AlarmRealtimeProvider

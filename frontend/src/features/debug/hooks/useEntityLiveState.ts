import { useState, useEffect, useCallback, useRef } from 'react'
import { wsManager } from '@/services'
import type { AlarmWebSocketMessage } from '@/types'

export function useEntityLiveState(entityId: string | null) {
  const [changedFields, setChangedFields] = useState<Set<string>>(new Set())
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearHighlights = useCallback(() => {
    setChangedFields(new Set())
  }, [])

  useEffect(() => {
    if (!entityId) return

    const unsubscribe = wsManager.onMessage((message: AlarmWebSocketMessage) => {
      if (message.type !== 'entity_sync') return

      const match = message.payload.entities.find((e) => e.entityId === entityId)
      if (!match) return

      const fields = new Set<string>()
      if (match.oldState !== match.newState) {
        fields.add('lastState')
        fields.add('lastChanged')
        fields.add('lastSeen')
      }

      if (fields.size > 0) {
        setChangedFields(fields)

        if (timeoutRef.current) clearTimeout(timeoutRef.current)
        timeoutRef.current = setTimeout(clearHighlights, 1500)
      }
    })

    return () => {
      unsubscribe()
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [entityId, clearHighlights])

  return changedFields
}

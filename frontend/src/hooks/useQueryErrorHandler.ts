import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { handleError } from '@/lib/errorHandler'
import { categorizeError } from '@/lib/errors'
import { FIVE_SECONDS_MS } from '@/lib/constants'

/**
 * Global handler for React Query errors
 * Place this once in your app (e.g., in App.tsx or a provider)
 */
export function useGlobalQueryErrorHandler() {
  const queryClient = useQueryClient()
  const handledErrors = useRef(new Set<string>())

  useEffect(() => {
    const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
      // Only handle new errors, not retries
      if (
        event.type === 'updated' &&
        event.query.state.status === 'error' &&
        event.query.state.fetchFailureCount === 1
      ) {
        const error = event.query.state.error
        const queryKey = JSON.stringify(event.query.queryKey)

        // Prevent duplicate handling
        if (handledErrors.current.has(queryKey)) return
        handledErrors.current.add(queryKey)

        // Clean up after a delay
        setTimeout(() => {
          handledErrors.current.delete(queryKey)
        }, FIVE_SECONDS_MS)

        // Categorize and handle
        const appError = categorizeError(error)

        // Auth errors - always handle (redirect to login)
        if (appError.category === 'auth') {
          handleError(error)
          return
        }

        // Network/server errors - show toast once
        if (appError.category === 'network' || appError.category === 'server') {
          handleError(error)
          return
        }

        // Other errors - let component handle via error state
        // (don't show global toast, component will show inline error)
      }
    })

    return unsubscribe
  }, [queryClient])
}

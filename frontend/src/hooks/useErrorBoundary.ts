import { useCallback, useState } from 'react'

/**
 * Hook to programmatically trigger error boundary reset
 */
export function useErrorBoundaryReset() {
  const [resetKey, setResetKey] = useState(0)

  const reset = useCallback(() => {
    setResetKey((k) => k + 1)
  }, [])

  return { resetKey, reset }
}

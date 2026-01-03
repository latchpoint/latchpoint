import { useCallback, useState } from 'react'
import type { ApiError } from '@/types'
import { isRecord } from '@/lib/typeGuards'

function isApiError(value: unknown): value is ApiError {
  return isRecord(value) && typeof value.message === 'string'
}

export function useFormErrors(): {
  fieldErrors: Record<string, string>
  generalError: string | null
  setFromError: (error: unknown) => void
  clearErrors: () => void
  clearFieldError: (field: string) => void
} {
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [generalError, setGeneralError] = useState<string | null>(null)

  const setFromError = useCallback((error: unknown) => {
    if (isApiError(error)) {
      const details = error.details || {}
      const hasFieldErrors = Object.keys(details).length > 0
      if (hasFieldErrors) {
        const firstErrors: Record<string, string> = {}
        for (const [field, messages] of Object.entries(details)) {
          firstErrors[field] = messages?.[0] || 'Invalid value'
        }
        setFieldErrors(firstErrors)
        setGeneralError(null)
        return
      }
      setFieldErrors({})
      setGeneralError(error.message || 'Request failed')
      return
    }

    if (error instanceof Error) {
      setFieldErrors({})
      setGeneralError(error.message || 'Request failed')
      return
    }

    setFieldErrors({})
    setGeneralError('An unexpected error occurred')
  }, [])

  const clearErrors = useCallback(() => {
    setFieldErrors({})
    setGeneralError(null)
  }, [])

  const clearFieldError = useCallback((field: string) => {
    setFieldErrors((prev) => {
      if (!(field in prev)) return prev
      const next = { ...prev }
      delete next[field]
      return next
    })
  }, [])

  return { fieldErrors, generalError, setFromError, clearErrors, clearFieldError }
}


import type { ApiError } from '@/types'
import { isRecord } from '@/lib/typeGuards'
import { getErrorMessage as getErrorMessageNew } from '@/types/errors'

/**
 * Error categories for different handling strategies
 */
export type ErrorCategory =
  | 'auth' // 401/403 - redirect to login
  | 'validation' // 400/422 - show field errors
  | 'not_found' // 404 - show not found message
  | 'network' // Network failures - show connection error
  | 'server' // 500+ - show server error
  | 'timeout' // Request timeout
  | 'unknown' // Fallback

/**
 * Structured error with category and metadata
 */
export interface AppError {
  category: ErrorCategory
  message: string
  code?: string
  errorCode?: string
  gateway?: string
  operation?: string
  details?: Record<string, string[]>
  originalError?: unknown
  timestamp: number
  recoverable: boolean
}

/**
 * Type guard for API errors
 */
export function isApiError(error: unknown): error is ApiError {
  return (
    isRecord(error) &&
    'message' in error &&
    typeof error.message === 'string'
  )
}

/**
 * Type guard for network errors
 */
export function isNetworkError(error: unknown): boolean {
  if (error instanceof TypeError) {
    return error.message.includes('fetch') || error.message.includes('network')
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    return false // Intentional abort, not a network error
  }
  return false
}

/**
 * Type guard for timeout errors
 */
export function isTimeoutError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

/**
 * Categorize any error into an AppError
 */
export function categorizeError(error: unknown): AppError {
  const timestamp = Date.now()

  // Network errors
  if (isNetworkError(error)) {
    return {
      category: 'network',
      message: 'Unable to connect to the server. Check your connection.',
      recoverable: true,
      timestamp,
      originalError: error,
    }
  }

  // Timeout errors
  if (isTimeoutError(error)) {
    return {
      category: 'timeout',
      message: 'Request timed out. Please try again.',
      recoverable: true,
      timestamp,
      originalError: error,
    }
  }

  // API errors with status codes
  if (isApiError(error)) {
    const code = parseInt(error.code || '0', 10)

    if (code === 401 || code === 403) {
      return {
        category: 'auth',
        message:
          code === 401
            ? 'Session expired. Please log in again.'
            : 'You do not have permission to perform this action.',
        code: error.code,
        errorCode: error.errorCode,
        gateway: error.gateway,
        operation: error.operation,
        recoverable: false,
        timestamp,
        originalError: error,
      }
    }

    if (code === 404) {
      return {
        category: 'not_found',
        message: error.message || 'The requested resource was not found.',
        code: error.code,
        errorCode: error.errorCode,
        gateway: error.gateway,
        operation: error.operation,
        recoverable: false,
        timestamp,
        originalError: error,
      }
    }

    if (code === 400 || code === 422) {
      return {
        category: 'validation',
        message: error.message || 'Please check your input and try again.',
        code: error.code,
        errorCode: error.errorCode,
        gateway: error.gateway,
        operation: error.operation,
        details: error.details,
        recoverable: true,
        timestamp,
        originalError: error,
      }
    }

    if (code >= 500) {
      return {
        category: 'server',
        message: 'The server encountered an error. Please try again later.',
        code: error.code,
        errorCode: error.errorCode,
        gateway: error.gateway,
        operation: error.operation,
        recoverable: true,
        timestamp,
        originalError: error,
      }
    }

    // API error without recognizable code
    return {
      category: 'unknown',
      message: error.message || 'An unexpected error occurred.',
      code: error.code,
      errorCode: error.errorCode,
      gateway: error.gateway,
      operation: error.operation,
      details: error.details,
      recoverable: true,
      timestamp,
      originalError: error,
    }
  }

  // Standard Error objects
  if (error instanceof Error) {
    return {
      category: 'unknown',
      message: error.message || 'An unexpected error occurred.',
      recoverable: true,
      timestamp,
      originalError: error,
    }
  }

  // Unknown error type
  return {
    category: 'unknown',
    message: 'An unexpected error occurred.',
    recoverable: true,
    timestamp,
    originalError: error,
  }
}

/**
 * Get user-friendly error message (legacy compatibility)
 * @deprecated Use getErrorMessage from @/types/errors instead
 */
export function getErrorMessage(error: unknown): string | undefined {
  if (!error) return undefined
  const message = getErrorMessageNew(error, '')
  return message || undefined
}

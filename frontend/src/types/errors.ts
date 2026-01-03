/**
 * Error type definitions and guards
 * Provides standardized error shapes and safe error message extraction
 */

import { isRecord } from '@/lib/typeGuards'

// ============================================================================
// Error Type Definitions
// ============================================================================

/**
 * Error with a message property
 */
export interface ErrorWithMessage {
  message: string
}

/**
 * Error with code and optional message
 */
export interface ErrorWithCode {
  code: string
  message?: string
}

/**
 * Error with numeric status code
 */
export interface ErrorWithStatus {
  status: number
  message?: string
}

/**
 * Combined error type with all common properties
 */
export interface StandardError {
  message: string
  code?: string
  status?: number
  details?: Record<string, unknown>
}

// ============================================================================
// Error Type Guards
// ============================================================================

/**
 * Check if error has a message property
 */
export function hasMessage(error: unknown): error is ErrorWithMessage {
  return isRecord(error) && typeof error.message === 'string'
}

/**
 * Check if error has a code property
 */
export function hasCode(error: unknown): error is ErrorWithCode {
  return isRecord(error) && typeof error.code === 'string'
}

/**
 * Check if error has a status property
 */
export function hasStatus(error: unknown): error is ErrorWithStatus {
  return isRecord(error) && typeof error.status === 'number'
}

/**
 * Check if value is an Error instance
 */
export function isErrorInstance(error: unknown): error is Error {
  return error instanceof Error
}

// ============================================================================
// Error Message Extraction
// ============================================================================

/**
 * Safely extract an error message from unknown error type
 * Returns a user-friendly message, never throws
 */
export function getErrorMessage(error: unknown, fallback = 'An unknown error occurred'): string {
  // Common case: "no error" values from libraries like react-query
  if (error == null) return ''

  // Standard Error instance
  if (isErrorInstance(error)) {
    return error.message || fallback
  }

  // Object with message property
  if (hasMessage(error)) {
    return error.message
  }

  // String error
  if (typeof error === 'string') {
    return error || fallback
  }

  // Fallback
  return fallback
}

/**
 * Extract error code if present
 */
export function getErrorCode(error: unknown): string | undefined {
  if (hasCode(error)) {
    return error.code
  }
  return undefined
}

/**
 * Extract error status if present
 */
export function getErrorStatus(error: unknown): number | undefined {
  if (hasStatus(error)) {
    return error.status
  }
  return undefined
}

/**
 * Convert unknown error to StandardError
 */
export function toStandardError(error: unknown): StandardError {
  return {
    message: getErrorMessage(error),
    code: getErrorCode(error),
    status: getErrorStatus(error),
    details: isRecord(error) ? error : undefined,
  }
}

// ============================================================================
// API Error Response Types
// ============================================================================

/**
 * Django REST Framework error response structure
 */
export interface ApiErrorResponse {
  // New envelope shape (ADR 0025)
  error?: {
    status?: string
    message?: string
    details?: Record<string, string[]>
    gateway?: string
    operation?: string
    error?: string
  }

  detail?: string
  message?: string
  non_field_errors?: string[]
  [field: string]: unknown
}

/**
 * Check if response is an API error response
 */
export function isApiErrorResponse(data: unknown): data is ApiErrorResponse {
  if (!isRecord(data)) return false

  // ADR 0025 envelope error
  if ('error' in data && isRecord(data.error)) {
    const message = data.error.message
    if (typeof message === 'string' && message.length > 0) return true
  }

  // Has at least one of the common error fields
  if ('detail' in data || 'message' in data || 'non_field_errors' in data) {
    return true
  }

  // Check for DRF field-level validation errors (e.g., {"code": ["This field may not be blank."]})
  for (const value of Object.values(data)) {
    if (Array.isArray(value) && value.length > 0 && typeof value[0] === 'string') {
      return true
    }
  }

  return false
}

/**
 * Extract error message from API error response
 */
export function getApiErrorMessage(response: ApiErrorResponse): string {
  // ADR 0025 envelope error
  if (response.error && typeof response.error.message === 'string' && response.error.message) {
    return response.error.message
  }

  // Try detail first
  if (response.detail && typeof response.detail === 'string') {
    return response.detail
  }

  // Try message
  if (response.message && typeof response.message === 'string') {
    return response.message
  }

  // Try non_field_errors
  if (Array.isArray(response.non_field_errors) && response.non_field_errors.length > 0) {
    return response.non_field_errors[0]
  }

  // Try to find first field error
  for (const [key, value] of Object.entries(response)) {
    if (key !== 'detail' && key !== 'message' && key !== 'non_field_errors') {
      if (Array.isArray(value) && value.length > 0 && typeof value[0] === 'string') {
        return `${key}: ${value[0]}`
      }
      if (typeof value === 'string') {
        return `${key}: ${value}`
      }
    }
  }

  return 'An error occurred'
}

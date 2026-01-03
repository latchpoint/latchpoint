/**
 * Runtime validation utilities
 * Provides assertion functions and safe parsing utilities
 */

import { isRecord } from './typeGuards'

// ============================================================================
// Assertion Functions
// ============================================================================

/**
 * Assert that a value is not null or undefined
 * Throws an error if the value is null/undefined
 */
export function assertDefined<T>(
  value: T | null | undefined,
  message?: string
): asserts value is T {
  if (value === null || value === undefined) {
    throw new Error(message ?? 'Value is null or undefined')
  }
}

/**
 * Assert that a value is a non-null object
 * Throws an error if the value is not a record
 */
export function assertRecord(value: unknown, message?: string): asserts value is Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(message ?? 'Value is not a record object')
  }
}

/**
 * Assert that a value is a string
 * Throws an error if the value is not a string
 */
export function assertString(value: unknown, message?: string): asserts value is string {
  if (typeof value !== 'string') {
    throw new Error(message ?? 'Value is not a string')
  }
}

/**
 * Assert that a value is a number
 * Throws an error if the value is not a number
 */
export function assertNumber(value: unknown, message?: string): asserts value is number {
  if (typeof value !== 'number') {
    throw new Error(message ?? 'Value is not a number')
  }
}

/**
 * Assert that a value is an array
 * Throws an error if the value is not an array
 */
export function assertArray(value: unknown, message?: string): asserts value is unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(message ?? 'Value is not an array')
  }
}

// ============================================================================
// Safe JSON Parsing
// ============================================================================

/**
 * Parse JSON string with type validation
 * Returns the parsed value if it passes the validator, throws otherwise
 */
export function parseJsonAs<T>(
  json: string,
  validator: (data: unknown) => data is T,
  errorMessage?: string
): T {
  try {
    const parsed = JSON.parse(json)
    if (!validator(parsed)) {
      throw new Error(errorMessage ?? 'Parsed JSON failed type validation')
    }
    return parsed
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error(`Invalid JSON: ${error.message}`)
    }
    throw error
  }
}

/**
 * Parse JSON string safely, returns undefined if parsing fails or validation fails
 */
export function parseJsonSafe<T>(
  json: string,
  validator: (data: unknown) => data is T
): T | undefined {
  try {
    const parsed = JSON.parse(json)
    return validator(parsed) ? parsed : undefined
  } catch {
    return undefined
  }
}

/**
 * Parse JSON string and return a record, or undefined if not a valid record
 */
export function parseJsonRecord(json: string): Record<string, unknown> | undefined {
  try {
    const parsed = JSON.parse(json)
    return isRecord(parsed) ? parsed : undefined
  } catch {
    return undefined
  }
}

// ============================================================================
// Safe Property Access
// ============================================================================

/**
 * Get a typed property from a record
 * Returns the property value if it passes validation, undefined otherwise
 */
export function getProperty<T>(
  obj: Record<string, unknown>,
  key: string,
  validator: (value: unknown) => value is T
): T | undefined {
  const value = obj[key]
  return validator(value) ? value : undefined
}

/**
 * Get a required typed property from a record
 * Throws an error if the property doesn't exist or fails validation
 */
export function getRequiredProperty<T>(
  obj: Record<string, unknown>,
  key: string,
  validator: (value: unknown) => value is T,
  errorMessage?: string
): T {
  const value = obj[key]
  if (!validator(value)) {
    throw new Error(errorMessage ?? `Property "${key}" is invalid or missing`)
  }
  return value
}

/**
 * Get a string property from a record
 */
export function getStringProperty(obj: Record<string, unknown>, key: string): string | undefined {
  const value = obj[key]
  return typeof value === 'string' ? value : undefined
}

/**
 * Get a number property from a record
 */
export function getNumberProperty(obj: Record<string, unknown>, key: string): number | undefined {
  const value = obj[key]
  return typeof value === 'number' ? value : undefined
}

/**
 * Get a boolean property from a record
 */
export function getBooleanProperty(obj: Record<string, unknown>, key: string): boolean | undefined {
  const value = obj[key]
  return typeof value === 'boolean' ? value : undefined
}

/**
 * Get a record property from a record
 */
export function getRecordProperty(
  obj: Record<string, unknown>,
  key: string
): Record<string, unknown> | undefined {
  const value = obj[key]
  return isRecord(value) ? value : undefined
}

// ============================================================================
// Safe Type Conversion
// ============================================================================

/**
 * Convert unknown value to string, with fallback
 */
export function toString(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return fallback
  return String(value)
}

/**
 * Convert unknown value to number, with fallback
 */
export function toNumber(value: unknown, fallback = 0): number {
  if (typeof value === 'number') return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    return Number.isNaN(parsed) ? fallback : parsed
  }
  return fallback
}

/**
 * Convert unknown value to boolean
 */
export function toBoolean(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    return value.toLowerCase() === 'true' || value === '1'
  }
  return Boolean(value)
}

/**
 * Form helpers for safe type handling of form values
 * Prevents unsafe type assertions from HTML form elements
 */

import React from 'react'

// ============================================================================
// Select Element Helpers
// ============================================================================

/**
 * Safely extract and validate a typed value from a select element
 * Returns the validated value, or the fallback if validation fails
 *
 * @example
 * const mode = getSelectValue(e, isAlarmArmMode, 'armed_away')
 */
export function getSelectValue<T extends string>(
  event: React.ChangeEvent<HTMLSelectElement>,
  validator: (value: string) => value is T,
  fallback: T
): T {
  const value = event.target.value
  return validator(value) ? value : fallback
}

/**
 * Safely extract a select value without validation
 * Returns the string value directly
 */
export function getSelectValueRaw(event: React.ChangeEvent<HTMLSelectElement>): string {
  return event.target.value
}

/**
 * Safely extract a select value with optional validation
 * Returns undefined if validation fails
 */
export function getSelectValueOptional<T extends string>(
  event: React.ChangeEvent<HTMLSelectElement>,
  validator: (value: string) => value is T
): T | undefined {
  const value = event.target.value
  return validator(value) ? value : undefined
}

// ============================================================================
// Input Element Helpers
// ============================================================================

/**
 * Safely extract string value from an input element
 */
export function getInputValue(event: React.ChangeEvent<HTMLInputElement>): string {
  return event.target.value
}

/**
 * Safely extract number value from an input element
 * Returns the fallback if the value is not a valid number
 */
export function getInputNumber(
  event: React.ChangeEvent<HTMLInputElement>,
  fallback = 0
): number {
  const value = event.target.value
  const parsed = Number(value)
  return Number.isNaN(parsed) ? fallback : parsed
}

/**
 * Safely extract boolean value from a checkbox input
 */
export function getCheckboxValue(event: React.ChangeEvent<HTMLInputElement>): boolean {
  return event.target.checked
}

// ============================================================================
// Textarea Element Helpers
// ============================================================================

/**
 * Safely extract string value from a textarea element
 */
export function getTextareaValue(event: React.ChangeEvent<HTMLTextAreaElement>): string {
  return event.target.value
}

// ============================================================================
// Generic Form Helpers
// ============================================================================

/**
 * Extract all form values as a record
 * Useful for FormData-based forms
 */
export function getFormValues(form: HTMLFormElement): Record<string, string> {
  const formData = new FormData(form)
  const values: Record<string, string> = {}

  formData.forEach((value, key) => {
    if (typeof value === 'string') {
      values[key] = value
    }
  })

  return values
}

/**
 * Extract a specific form field value
 */
export function getFormFieldValue(form: HTMLFormElement, fieldName: string): string | null {
  const formData = new FormData(form)
  const value = formData.get(fieldName)
  return typeof value === 'string' ? value : null
}

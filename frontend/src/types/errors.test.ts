import { describe, expect, it } from 'vitest'
import { getApiErrorMessage, getErrorMessage, isApiErrorResponse } from '@/types/errors'

describe('types/errors', () => {
  describe('getErrorMessage', () => {
    it('returns empty string for null/undefined', () => {
      expect(getErrorMessage(null)).toBe('')
      expect(getErrorMessage(undefined)).toBe('')
    })

    it('extracts message from Error instances', () => {
      expect(getErrorMessage(new Error('boom'))).toBe('boom')
    })

    it('extracts message from objects with message', () => {
      expect(getErrorMessage({ message: 'nope' })).toBe('nope')
    })

    it('falls back for unknown error types', () => {
      expect(getErrorMessage(123, 'fallback')).toBe('fallback')
    })
  })

  describe('isApiErrorResponse', () => {
    it('detects ADR 0025 envelope errors', () => {
      expect(isApiErrorResponse({ error: { message: 'bad' } })).toBe(true)
    })

    it('detects DRF detail errors', () => {
      expect(isApiErrorResponse({ detail: 'nope' })).toBe(true)
    })

    it('detects field validation errors', () => {
      expect(isApiErrorResponse({ email: ['Enter a valid email.'] })).toBe(true)
    })

    it('returns false for non-error objects', () => {
      expect(isApiErrorResponse({ ok: true })).toBe(false)
    })
  })

  describe('getApiErrorMessage', () => {
    it('prefers envelope error message', () => {
      expect(getApiErrorMessage({ error: { message: 'Envelope error' } })).toBe('Envelope error')
    })

    it('falls back to detail', () => {
      expect(getApiErrorMessage({ detail: 'Detail error' })).toBe('Detail error')
    })

    it('falls back to non_field_errors', () => {
      expect(getApiErrorMessage({ non_field_errors: ['Nope'] })).toBe('Nope')
    })

    it('formats field errors as \"field: message\"', () => {
      expect(getApiErrorMessage({ email: ['Invalid'] })).toBe('email: Invalid')
    })
  })
})


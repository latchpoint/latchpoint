import { describe, expect, it, vi } from 'vitest'
import { categorizeError } from '@/lib/errors'

describe('categorizeError', () => {
  it('categorizes network TypeError errors', () => {
    vi.spyOn(Date, 'now').mockReturnValue(123)

    const err = new TypeError('Failed to fetch')
    const result = categorizeError(err)

    expect(result).toMatchObject({
      category: 'network',
      message: 'Unable to connect to the server. Check your connection.',
      recoverable: true,
      timestamp: 123,
      originalError: err,
    })
  })

  it('categorizes AbortError as timeout', () => {
    vi.spyOn(Date, 'now').mockReturnValue(456)

    const err = new DOMException('The operation was aborted.', 'AbortError')
    const result = categorizeError(err)

    expect(result).toMatchObject({
      category: 'timeout',
      message: 'Request timed out. Please try again.',
      recoverable: true,
      timestamp: 456,
      originalError: err,
    })
  })

  it('categorizes API 401 as auth', () => {
    vi.spyOn(Date, 'now').mockReturnValue(789)

    const err = { message: 'Unauthorized', code: '401', errorCode: 'auth_error' }
    const result = categorizeError(err)

    expect(result).toMatchObject({
      category: 'auth',
      message: 'Session expired. Please log in again.',
      code: '401',
      errorCode: 'auth_error',
      recoverable: false,
      timestamp: 789,
      originalError: err,
    })
  })

  it('categorizes API 422 as validation and preserves details', () => {
    const err = {
      message: 'One or more fields failed validation.',
      code: '422',
      errorCode: 'validation_error',
      details: { email: ['Enter a valid email address.'] },
    }
    const result = categorizeError(err)

    expect(result.category).toBe('validation')
    expect(result.recoverable).toBe(true)
    expect(result.details).toEqual({ email: ['Enter a valid email address.'] })
  })
})


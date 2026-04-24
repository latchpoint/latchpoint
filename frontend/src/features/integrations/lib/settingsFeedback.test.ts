import { describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import {
  categorizeSettingsError,
  useSettingsActionFeedback,
} from '@/features/integrations/lib/settingsFeedback'

describe('categorizeSettingsError', () => {
  it('AC-1: returns validation category for HTTP 400 with field errors', () => {
    const err = {
      message: 'Validation failed',
      code: '400',
      details: { host: ['This field is required.'] },
    }
    const result = categorizeSettingsError(err, 'Save')
    expect(result.category).toBe('validation')
    expect(result.message).toContain('host')
    expect(result.message).toContain('required')
  })

  it('AC-2: returns auth category for HTTP 401 and 403', () => {
    const err401 = { message: 'Unauthorized', code: '401' }
    const err403 = { message: 'Forbidden', code: '403' }
    const r401 = categorizeSettingsError(err401, 'Save')
    const r403 = categorizeSettingsError(err403, 'Refresh')
    expect(r401.category).toBe('auth')
    expect(r403.category).toBe('auth')
    expect(r401.message).toBe("Save failed: you don't have permission to change these settings.")
    expect(r403.message).toBe("Refresh failed: you don't have permission to change these settings.")
  })

  it('AC-3: returns network category when fetch threw a TypeError', () => {
    const err = new TypeError('Failed to fetch')
    const result = categorizeSettingsError(err, 'Refresh')
    expect(result.category).toBe('network')
    expect(result.message).toContain('Refresh failed')
    expect(result.message.toLowerCase()).toContain('connection')
  })

  it('AC-4: returns server category for HTTP >= 500 and appends detail', () => {
    const err = {
      message: 'Internal server error',
      code: '503',
      details: { detail: ['database unreachable'] },
    }
    const result = categorizeSettingsError(err, 'Save')
    expect(result.category).toBe('server')
    expect(result.message).toContain('Save failed')
    expect(result.message).toContain('server')
    expect(result.message).toContain('database unreachable')
  })

  it('AC-5: returns unknown category with getErrorMessage fallback', () => {
    const err = new Error('Something weird happened')
    const result = categorizeSettingsError(err, 'Save')
    expect(result.category).toBe('unknown')
    expect(result.message).toBe('Save failed: Something weird happened')
  })
})

describe('useSettingsActionFeedback', () => {
  it('AC-6: runSave on success sets success notice and returns the value', async () => {
    const { result } = renderHook(() => useSettingsActionFeedback())
    let returned: unknown
    await act(async () => {
      returned = await result.current.runSave(async () => 42, 'Saved ok.')
    })
    expect(returned).toBe(42)
    expect(result.current.notice).toBe('Saved ok.')
    expect(result.current.noticeVariant).toBe('success')
    expect(result.current.error).toBeNull()
  })
})

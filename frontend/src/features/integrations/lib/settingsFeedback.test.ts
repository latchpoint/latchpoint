import { describe, expect, it } from 'vitest'
import { categorizeSettingsError } from '@/features/integrations/lib/settingsFeedback'

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
})

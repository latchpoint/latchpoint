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
})

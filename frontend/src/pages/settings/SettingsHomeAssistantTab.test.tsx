import { describe, expect, it } from 'vitest'

describe('SettingsHomeAssistantTab', () => {
  it('imports', async () => {
    const mod = await import('./SettingsHomeAssistantTab')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('SettingsNotificationsTab', () => {
  it('imports', async () => {
    const mod = await import('./SettingsNotificationsTab')
    expect(mod).toBeTruthy()
  })
})

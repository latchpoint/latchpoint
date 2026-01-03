import { describe, expect, it } from 'vitest'

describe('SettingsAlarmTab', () => {
  it('imports', async () => {
    const mod = await import('./SettingsAlarmTab')
    expect(mod).toBeTruthy()
  })
})

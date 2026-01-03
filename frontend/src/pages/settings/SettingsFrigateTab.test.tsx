import { describe, expect, it } from 'vitest'

describe('SettingsFrigateTab', () => {
  it('imports', async () => {
    const mod = await import('./SettingsFrigateTab')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('AlarmPanelContainer', () => {
  it('imports', async () => {
    const mod = await import('./AlarmPanelContainer')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('AlarmPanel', () => {
  it('exports AlarmPanel and AlarmPanelView', async () => {
    const mod = await import('./AlarmPanel')
    expect(mod.AlarmPanel).toBeTruthy()
    expect(mod.AlarmPanelView).toBeTruthy()
    expect(mod.default).toBeTruthy()
  })
})

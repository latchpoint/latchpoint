import { describe, expect, it } from 'vitest'

describe('AlarmPanelView', () => {
  it('imports', async () => {
    const mod = await import('./AlarmPanelView')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('SettingsTabShell', () => {
  it('imports', async () => {
    const mod = await import('./SettingsTabShell')
    expect(mod).toBeTruthy()
  })
})

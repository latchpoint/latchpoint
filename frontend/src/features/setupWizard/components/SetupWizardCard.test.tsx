import { describe, expect, it } from 'vitest'

describe('SetupWizardCard', () => {
  it('imports', async () => {
    const mod = await import('./SetupWizardCard')
    expect(mod).toBeTruthy()
  })
})

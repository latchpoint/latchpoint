import { describe, expect, it } from 'vitest'

describe('useSetupZwavejsModel', () => {
  it('imports', async () => {
    const mod = await import('./useSetupZwavejsModel')
    expect(mod).toBeTruthy()
  })
})

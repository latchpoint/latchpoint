import { describe, expect, it } from 'vitest'

describe('CodeTemporaryRestrictionsFields', () => {
  it('imports', async () => {
    const mod = await import('./CodeTemporaryRestrictionsFields')
    expect(mod).toBeTruthy()
  })
})

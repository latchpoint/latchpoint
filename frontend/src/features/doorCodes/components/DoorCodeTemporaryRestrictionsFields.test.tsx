import { describe, expect, it } from 'vitest'

describe('DoorCodeTemporaryRestrictionsFields', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeTemporaryRestrictionsFields')
    expect(mod).toBeTruthy()
  })
})

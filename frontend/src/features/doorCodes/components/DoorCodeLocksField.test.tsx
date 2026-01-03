import { describe, expect, it } from 'vitest'

describe('DoorCodeLocksField', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeLocksField')
    expect(mod).toBeTruthy()
  })
})

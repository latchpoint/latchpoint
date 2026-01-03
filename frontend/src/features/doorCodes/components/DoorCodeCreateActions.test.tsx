import { describe, expect, it } from 'vitest'

describe('DoorCodeCreateActions', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeCreateActions')
    expect(mod).toBeTruthy()
  })
})

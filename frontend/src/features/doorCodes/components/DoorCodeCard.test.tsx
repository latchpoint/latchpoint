import { describe, expect, it } from 'vitest'

describe('DoorCodeCard', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeCard')
    expect(mod).toBeTruthy()
  })
})

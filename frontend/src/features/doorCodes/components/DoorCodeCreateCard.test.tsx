import { describe, expect, it } from 'vitest'

describe('DoorCodeCreateCard', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeCreateCard')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('DoorCodeLocksPicker', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeLocksPicker')
    expect(mod).toBeTruthy()
  })
})

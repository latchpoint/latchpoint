import { describe, expect, it } from 'vitest'

describe('DoorCodeEditContainer', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeEditContainer')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('DoorCodeActiveToggle', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeActiveToggle')
    expect(mod).toBeTruthy()
  })
})

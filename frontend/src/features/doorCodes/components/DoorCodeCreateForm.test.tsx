import { describe, expect, it } from 'vitest'

describe('DoorCodeCreateForm', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeCreateForm')
    expect(mod).toBeTruthy()
  })
})

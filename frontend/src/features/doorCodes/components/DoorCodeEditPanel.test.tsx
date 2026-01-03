import { describe, expect, it } from 'vitest'

describe('DoorCodeEditPanel', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeEditPanel')
    expect(mod).toBeTruthy()
  })
})

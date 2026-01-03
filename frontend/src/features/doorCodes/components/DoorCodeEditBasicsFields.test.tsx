import { describe, expect, it } from 'vitest'

describe('DoorCodeEditBasicsFields', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeEditBasicsFields')
    expect(mod).toBeTruthy()
  })
})

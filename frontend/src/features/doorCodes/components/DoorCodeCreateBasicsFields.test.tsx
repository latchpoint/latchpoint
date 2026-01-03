import { describe, expect, it } from 'vitest'

describe('DoorCodeCreateBasicsFields', () => {
  it('imports', async () => {
    const mod = await import('./DoorCodeCreateBasicsFields')
    expect(mod).toBeTruthy()
  })
})

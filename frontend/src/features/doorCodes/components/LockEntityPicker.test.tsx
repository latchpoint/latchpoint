import { describe, expect, it } from 'vitest'

describe('LockEntityPicker', () => {
  it('imports', async () => {
    const mod = await import('./LockEntityPicker')
    expect(mod).toBeTruthy()
  })
})

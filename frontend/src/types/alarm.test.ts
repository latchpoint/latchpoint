import { describe, expect, it } from 'vitest'

describe('alarm', () => {
  it('imports', async () => {
    const mod = await import('./alarm')
    expect(mod).toBeTruthy()
  })
})

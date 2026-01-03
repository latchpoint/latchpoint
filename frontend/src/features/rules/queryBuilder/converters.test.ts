import { describe, expect, it } from 'vitest'

describe('converters', () => {
  it('imports', async () => {
    const mod = await import('./converters')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('FrigateValueEditor', () => {
  it('imports', async () => {
    const mod = await import('./FrigateValueEditor')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('button-variants', () => {
  it('imports', async () => {
    const mod = await import('./button-variants')
    expect(mod).toBeTruthy()
  })
})

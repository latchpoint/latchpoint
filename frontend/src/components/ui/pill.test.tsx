import { describe, expect, it } from 'vitest'

describe('pill', () => {
  it('imports', async () => {
    const mod = await import('./pill')
    expect(mod).toBeTruthy()
  })
})

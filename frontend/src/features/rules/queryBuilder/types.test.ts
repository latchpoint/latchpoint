import { describe, expect, it } from 'vitest'

describe('types', () => {
  it('imports', async () => {
    const mod = await import('./types')
    expect(mod).toBeTruthy()
  })
})

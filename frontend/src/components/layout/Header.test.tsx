import { describe, expect, it } from 'vitest'

describe('Header', () => {
  it('imports', async () => {
    const mod = await import('./Header')
    expect(mod).toBeTruthy()
  })
})

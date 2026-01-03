import { describe, expect, it } from 'vitest'

describe('Sidebar', () => {
  it('imports', async () => {
    const mod = await import('./Sidebar')
    expect(mod).toBeTruthy()
  })
})

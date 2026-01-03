import { describe, expect, it } from 'vitest'

describe('hydrateBuilderFromRule', () => {
  it('imports', async () => {
    const mod = await import('./hydrateBuilderFromRule')
    expect(mod).toBeTruthy()
  })
})

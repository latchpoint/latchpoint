import { describe, expect, it } from 'vitest'

describe('CodeEditPanel', () => {
  it('imports', async () => {
    const mod = await import('./CodeEditPanel')
    expect(mod).toBeTruthy()
  })
})

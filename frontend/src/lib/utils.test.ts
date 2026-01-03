import { describe, expect, it } from 'vitest'

describe('utils', () => {
  it('imports', async () => {
    const mod = await import('./utils')
    expect(mod).toBeTruthy()
  })
})

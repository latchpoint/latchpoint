import { describe, expect, it } from 'vitest'

describe('checkbox', () => {
  it('imports', async () => {
    const mod = await import('./checkbox')
    expect(mod).toBeTruthy()
  })
})

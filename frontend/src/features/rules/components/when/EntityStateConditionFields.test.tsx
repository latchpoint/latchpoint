import { describe, expect, it } from 'vitest'

describe('EntityStateConditionFields', () => {
  it('imports', async () => {
    const mod = await import('./EntityStateConditionFields')
    expect(mod).toBeTruthy()
  })
})

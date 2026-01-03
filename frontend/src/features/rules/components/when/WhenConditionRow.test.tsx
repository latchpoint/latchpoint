import { describe, expect, it } from 'vitest'

describe('WhenConditionRow', () => {
  it('imports', async () => {
    const mod = await import('./WhenConditionRow')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('RuleCooldownAndEntitiesFields', () => {
  it('imports', async () => {
    const mod = await import('./RuleCooldownAndEntitiesFields')
    expect(mod).toBeTruthy()
  })
})

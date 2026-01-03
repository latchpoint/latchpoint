import { describe, expect, it } from 'vitest'

describe('ActionsEditor', () => {
  it('imports', async () => {
    const mod = await import('./ActionsEditor')
    expect(mod).toBeTruthy()
  })
})

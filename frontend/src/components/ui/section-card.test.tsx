import { describe, expect, it } from 'vitest'

describe('section-card', () => {
  it('imports', async () => {
    const mod = await import('./section-card')
    expect(mod).toBeTruthy()
  })
})

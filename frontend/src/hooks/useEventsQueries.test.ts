import { describe, expect, it } from 'vitest'

describe('useEventsQueries', () => {
  it('imports', async () => {
    const mod = await import('./useEventsQueries')
    expect(mod).toBeTruthy()
  })
})

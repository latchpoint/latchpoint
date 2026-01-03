import { describe, expect, it } from 'vitest'

describe('useEventsPageModel', () => {
  it('imports', async () => {
    const mod = await import('./useEventsPageModel')
    expect(mod).toBeTruthy()
  })
})

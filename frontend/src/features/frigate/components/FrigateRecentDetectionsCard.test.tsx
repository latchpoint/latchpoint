import { describe, expect, it } from 'vitest'

describe('FrigateRecentDetectionsCard', () => {
  it('imports', async () => {
    const mod = await import('./FrigateRecentDetectionsCard')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('FrigateDetectionDetailDialog', () => {
  it('imports', async () => {
    const mod = await import('./FrigateDetectionDetailDialog')
    expect(mod).toBeTruthy()
  })
})

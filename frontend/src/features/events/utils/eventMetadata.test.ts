import { describe, expect, it } from 'vitest'

describe('eventMetadata', () => {
  it('imports', async () => {
    const mod = await import('./eventMetadata')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('CodeEntryModal', () => {
  it('imports', async () => {
    const mod = await import('./CodeEntryModal')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('FrigateStringListPicker', () => {
  it('imports', async () => {
    const mod = await import('./FrigateStringListPicker')
    expect(mod).toBeTruthy()
  })
})

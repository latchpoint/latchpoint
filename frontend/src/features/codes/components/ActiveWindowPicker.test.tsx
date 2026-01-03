import { describe, expect, it } from 'vitest'

describe('ActiveWindowPicker', () => {
  it('imports', async () => {
    const mod = await import('./ActiveWindowPicker')
    expect(mod).toBeTruthy()
  })
})

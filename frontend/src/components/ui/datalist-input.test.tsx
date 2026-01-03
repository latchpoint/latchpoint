import { describe, expect, it } from 'vitest'

describe('datalist-input', () => {
  it('imports', async () => {
    const mod = await import('./datalist-input')
    expect(mod).toBeTruthy()
  })
})

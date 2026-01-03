import { describe, expect, it } from 'vitest'

describe('form-field', () => {
  it('imports', async () => {
    const mod = await import('./form-field')
    expect(mod).toBeTruthy()
  })
})

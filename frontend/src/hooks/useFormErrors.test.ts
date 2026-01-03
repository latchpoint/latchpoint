import { describe, expect, it } from 'vitest'

describe('useFormErrors', () => {
  it('imports', async () => {
    const mod = await import('./useFormErrors')
    expect(mod).toBeTruthy()
  })
})

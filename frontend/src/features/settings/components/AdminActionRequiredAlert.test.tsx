import { describe, expect, it } from 'vitest'

describe('AdminActionRequiredAlert', () => {
  it('imports', async () => {
    const mod = await import('./AdminActionRequiredAlert')
    expect(mod).toBeTruthy()
  })
})

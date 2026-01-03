import { describe, expect, it } from 'vitest'

describe('button', () => {
  it('imports', async () => {
    const mod = await import('./button')
    expect(mod).toBeTruthy()
  })
})

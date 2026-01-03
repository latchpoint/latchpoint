import { describe, expect, it } from 'vitest'

describe('Keypad', () => {
  it('imports', async () => {
    const mod = await import('./Keypad')
    expect(mod).toBeTruthy()
  })
})

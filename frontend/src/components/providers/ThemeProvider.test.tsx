import { describe, expect, it } from 'vitest'

describe('ThemeProvider', () => {
  it('imports', async () => {
    const mod = await import('./ThemeProvider')
    expect(mod).toBeTruthy()
  })
})

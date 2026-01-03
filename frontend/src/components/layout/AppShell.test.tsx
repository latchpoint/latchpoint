import { describe, expect, it } from 'vitest'

describe('AppShell', () => {
  it('imports', async () => {
    const mod = await import('./AppShell')
    expect(mod).toBeTruthy()
  })
})

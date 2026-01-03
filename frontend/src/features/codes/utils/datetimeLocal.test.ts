import { describe, expect, it } from 'vitest'

describe('datetimeLocal', () => {
  it('imports', async () => {
    const mod = await import('./datetimeLocal')
    expect(mod).toBeTruthy()
  })
})

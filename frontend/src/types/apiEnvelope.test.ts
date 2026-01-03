import { describe, expect, it } from 'vitest'

describe('apiEnvelope', () => {
  it('imports', async () => {
    const mod = await import('./apiEnvelope')
    expect(mod).toBeTruthy()
  })
})

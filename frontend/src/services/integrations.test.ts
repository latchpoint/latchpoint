import { describe, expect, it } from 'vitest'

describe('integrations', () => {
  it('imports', async () => {
    const mod = await import('./integrations')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('notifications', () => {
  it('imports', async () => {
    const mod = await import('./notifications')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('PushbulletNotificationOptions', () => {
  it('imports', async () => {
    const mod = await import('./PushbulletNotificationOptions')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('homeAssistant', () => {
  it('imports', async () => {
    const mod = await import('./homeAssistant')
    expect(mod).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

describe('useHomeAssistant', () => {
  it('imports', async () => {
    const mod = await import('./useHomeAssistant')
    expect(mod).toBeTruthy()
  })
})

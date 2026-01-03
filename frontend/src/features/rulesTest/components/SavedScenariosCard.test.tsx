import { describe, expect, it } from 'vitest'

describe('SavedScenariosCard', () => {
  it('imports', async () => {
    const mod = await import('./SavedScenariosCard')
    expect(mod).toBeTruthy()
  })
})

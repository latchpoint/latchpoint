import { describe, expect, it } from 'vitest'

describe('FrigatePersonDetectedConditionFields', () => {
  it('imports', async () => {
    const mod = await import('./FrigatePersonDetectedConditionFields')
    expect(mod).toBeTruthy()
  })
})

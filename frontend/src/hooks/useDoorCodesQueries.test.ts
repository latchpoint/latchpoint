import { describe, expect, it } from 'vitest'

describe('useDoorCodesQueries', () => {
  it('imports', async () => {
    const mod = await import('./useDoorCodesQueries')
    expect(mod).toBeTruthy()
  })
})

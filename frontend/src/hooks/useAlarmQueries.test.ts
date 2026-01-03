import { describe, expect, it } from 'vitest'

describe('useAlarmQueries', () => {
  it('imports', async () => {
    const mod = await import('./useAlarmQueries')
    expect(mod).toBeTruthy()
  })
})

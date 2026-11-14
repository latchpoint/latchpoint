import { describe, expect, it } from 'vitest'
import { limitOfUses, usesText } from './maxUses'

describe('maxUses', () => {
  it('imports', async () => {
    const mod = await import('./maxUses')
    expect(mod).toBeTruthy()
  })

  it('gives a one-time code without a max one use, like the backend', () => {
    expect(limitOfUses('one_time', null)).toBe(1)
    expect(limitOfUses('one_time', 3)).toBe(3)
    expect(limitOfUses('permanent', null)).toBeNull()
    expect(limitOfUses('temporary', 2)).toBe(2)
  })

  it('says the uses out of the limit when there is one', () => {
    expect(usesText({ codeType: 'permanent', maxUses: 5, usesCount: 2 })).toBe('Uses: 2 of 5')
    expect(usesText({ codeType: 'permanent', maxUses: null, usesCount: 2 })).toBe('Uses: 2')
    expect(usesText({ codeType: 'one_time', maxUses: null, usesCount: 0 })).toBe('Uses: 0 of 1')
  })
})

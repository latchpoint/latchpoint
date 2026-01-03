import { describe, expect, it } from 'vitest'

describe('ConfirmDeleteModal', () => {
  it('imports', async () => {
    const mod = await import('./ConfirmDeleteModal')
    expect(mod).toBeTruthy()
  })
})

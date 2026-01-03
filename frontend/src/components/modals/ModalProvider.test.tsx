import { describe, expect, it } from 'vitest'

describe('ModalProvider', () => {
  it('imports', async () => {
    const mod = await import('./ModalProvider')
    expect(mod).toBeTruthy()
  })
})

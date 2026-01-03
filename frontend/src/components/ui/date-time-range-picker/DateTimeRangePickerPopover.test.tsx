import { describe, expect, it } from 'vitest'

describe('DateTimeRangePickerPopover', () => {
  it('imports', async () => {
    const mod = await import('./DateTimeRangePickerPopover')
    expect(mod).toBeTruthy()
  })
})

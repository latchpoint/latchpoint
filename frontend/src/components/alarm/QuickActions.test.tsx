import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QuickActions } from './QuickActions'

describe('QuickActions', () => {
  it('renders only the requested actions and calls handlers', async () => {
    const user = userEvent.setup()
    const onDisarm = vi.fn()
    const onPanic = vi.fn()
    const onCancel = vi.fn()

    render(
      <QuickActions
        onDisarm={onDisarm}
        onPanic={onPanic}
        onCancel={onCancel}
        showCancel={true}
        showPanic={true}
        showDisarm={true}
      />
    )

    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /disarm/i }))
    expect(onDisarm).toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /panic/i }))
    expect(onPanic).toHaveBeenCalled()
  })

  it('disables buttons when disabled', async () => {
    const user = userEvent.setup()
    const onDisarm = vi.fn()
    render(<QuickActions onDisarm={onDisarm} disabled />)

    const disarm = screen.getByRole('button', { name: /disarm/i })
    expect(disarm).toBeDisabled()
    await user.click(disarm)
    expect(onDisarm).not.toHaveBeenCalled()
  })
})

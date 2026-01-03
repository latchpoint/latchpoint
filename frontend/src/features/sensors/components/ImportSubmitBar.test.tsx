import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { ImportSubmitBar } from '@/features/sensors/components/ImportSubmitBar'

describe('ImportSubmitBar', () => {
  it('disables submit when nothing selected', () => {
    renderWithProviders(<ImportSubmitBar selectedCount={0} isSubmitting={false} progress={null} onSubmit={() => {}} />)
    expect(screen.getByRole('button', { name: /import selected/i })).toBeDisabled()
  })

  it('shows progress and calls submit', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    renderWithProviders(
      <ImportSubmitBar selectedCount={2} isSubmitting={false} progress={{ current: 1, total: 2 }} onSubmit={onSubmit} />
    )
    expect(screen.getByText(/importing 1\/2/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /import selected/i }))
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })
})


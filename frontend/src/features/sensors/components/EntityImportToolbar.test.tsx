import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { EntityImportToolbar } from '@/features/sensors/components/EntityImportToolbar'

describe('EntityImportToolbar', () => {
  it('updates query and view mode', async () => {
    const user = userEvent.setup()
    const onQueryChange = vi.fn()
    const onViewModeChange = vi.fn()

    renderWithProviders(
      <EntityImportToolbar
        query=""
        onQueryChange={onQueryChange}
        viewMode="available"
        onViewModeChange={onViewModeChange}
        availableCount={2}
        importedCount={1}
        allCount={3}
      />
    )

    await user.type(screen.getByPlaceholderText(/search/i), 'door')
    expect(onQueryChange).toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /imported/i }))
    expect(onViewModeChange).toHaveBeenCalledWith('imported')
  })
})


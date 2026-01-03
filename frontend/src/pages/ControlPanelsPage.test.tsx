import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import userEvent from '@testing-library/user-event'
import ControlPanelsPage from '@/pages/ControlPanelsPage'
import { UserRole } from '@/lib/constants'

let currentUser: any = null

vi.mock('@/hooks/useAuthQueries', () => {
  return {
    useCurrentUserQuery: () => ({ data: currentUser }),
  }
})

vi.mock('@/hooks/useControlPanels', () => {
  return {
    useControlPanelsQuery: () => ({ data: [], isLoading: false }),
    useCreateControlPanelMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useUpdateControlPanelMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useDeleteControlPanelMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useTestControlPanelMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
  }
})

vi.mock('@/hooks/useZwavejs', () => {
  return {
    useZwavejsStatusQuery: () => ({ data: { enabled: true, homeId: 1 } }),
    useZwavejsNodesQuery: () => ({ data: { nodes: [] }, isLoading: false }),
  }
})

describe('ControlPanelsPage', () => {
  beforeEach(() => {
    currentUser = { id: 'u1', role: UserRole.USER }
  })

  it('disables Add button for non-admins', () => {
    renderWithProviders(<ControlPanelsPage />)
    const addButton = screen.getByRole('button', { name: 'Add' })
    expect(addButton).toBeDisabled()
    expect(addButton).toHaveAttribute('title', 'Admin role required')
  })

  it('shows add form when admin clicks Add', async () => {
    const user = userEvent.setup()
    currentUser = { id: 'a1', role: UserRole.ADMIN }
    renderWithProviders(<ControlPanelsPage />)

    await user.click(screen.getByRole('button', { name: 'Add' }))
    expect(screen.getByText(/add control panel/i)).toBeInTheDocument()
    expect(screen.getByText('Type')).toBeInTheDocument()
    expect(screen.getByText('Name')).toBeInTheDocument()
  })
})


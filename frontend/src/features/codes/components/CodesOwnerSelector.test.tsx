import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { CodesOwnerSelector } from '@/features/codes/components/CodesOwnerSelector'
import type { User } from '@/types'

const users: User[] = [
  {
    id: 'u1',
    email: 'a@example.com',
    displayName: 'Alice',
    role: 'user',
    isActive: true,
    has2FA: false,
    createdAt: '2025-01-01T00:00:00Z',
    lastLogin: null,
  },
  {
    id: 'u2',
    email: 'b@example.com',
    displayName: 'Bob',
    role: 'admin',
    isActive: true,
    has2FA: true,
    createdAt: '2025-01-01T00:00:00Z',
    lastLogin: null,
  },
]

describe('CodesOwnerSelector', () => {
  it('renders options and calls onChange', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()

    renderWithProviders(
      <CodesOwnerSelector users={users} value="u1" onChange={onChange} isLoading={false} error={null} />
    )

    await user.selectOptions(screen.getByLabelText(/owner/i), ['u2'])
    expect(onChange).toHaveBeenCalledWith('u2')
  })

  it('disables select when loading or error and shows error message', () => {
    const { rerender } = renderWithProviders(
      <CodesOwnerSelector users={users} value="u1" onChange={() => {}} isLoading={true} error={null} />
    )

    expect(screen.getByLabelText(/owner/i)).toBeDisabled()

    rerender(
      <CodesOwnerSelector users={users} value="u1" onChange={() => {}} isLoading={false} error={new Error('boom')} />
    )

    expect(screen.getByLabelText(/owner/i)).toBeDisabled()
    expect(screen.getByText(/failed to load users/i)).toBeInTheDocument()
  })
})


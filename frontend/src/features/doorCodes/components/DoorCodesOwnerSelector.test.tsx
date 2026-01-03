import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/render'
import { DoorCodesOwnerSelector } from '@/features/doorCodes/components/DoorCodesOwnerSelector'
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
]

describe('DoorCodesOwnerSelector', () => {
  it('calls onChange when selecting a new owner', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()

    renderWithProviders(
      <DoorCodesOwnerSelector users={users} value="u1" onChange={onChange} isLoading={false} error={null} />
    )

    await user.selectOptions(screen.getByLabelText(/owner/i), ['u1'])
    expect(onChange).toHaveBeenCalledWith('u1')
  })
})


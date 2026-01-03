import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import CodesPage from '@/pages/CodesPage'
import { UserRole } from '@/lib/constants'

let currentUser: any = null
let lastUsersQueryArg: any = null

vi.mock('@/hooks/useAuthQueries', () => {
  return {
    useCurrentUserQuery: () => ({ data: currentUser }),
  }
})

vi.mock('@/hooks/useCodesQueries', () => {
  return {
    useUsersQuery: (isAdmin: boolean) => {
      lastUsersQueryArg = isAdmin
      return { data: [], isLoading: false, isError: false, error: null }
    },
    useCodesQuery: () => ({ data: [], isLoading: false, isError: false, error: null }),
    useCreateCodeMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useUpdateCodeMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
  }
})

vi.mock('@/features/codes/components/CodeCard', () => {
  return { CodeCard: () => <div>CodeCard</div> }
})
vi.mock('@/features/codes/components/CodeCreateCard', () => {
  return { CodeCreateCard: () => <div>CodeCreateCard</div> }
})
vi.mock('@/features/codes/components/CodesOwnerSelector', () => {
  return { CodesOwnerSelector: () => <div>CodesOwnerSelector</div> }
})

describe('CodesPage', () => {
  beforeEach(() => {
    currentUser = { id: 'u1', role: UserRole.USER, displayName: 'User', email: 'u@example.com' }
    lastUsersQueryArg = null
  })

  it('shows non-admin copy for regular users', () => {
    renderWithProviders(<CodesPage />)
    expect(screen.getByText(/your codes/i)).toBeInTheDocument()
    expect(lastUsersQueryArg).toBe(false)
  })

  it('shows admin management section for admins', () => {
    currentUser = { id: 'a1', role: UserRole.ADMIN, displayName: 'Admin', email: 'a@example.com' }
    renderWithProviders(<CodesPage />)
    expect(screen.getByText(/manage user codes/i)).toBeInTheDocument()
    expect(screen.getByText('CodesOwnerSelector')).toBeInTheDocument()
    expect(screen.getByText('CodeCreateCard')).toBeInTheDocument()
    expect(lastUsersQueryArg).toBe(true)
  })
})


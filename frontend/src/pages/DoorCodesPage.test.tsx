import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/render'
import DoorCodesPage from '@/pages/DoorCodesPage'
import { UserRole } from '@/lib/constants'

let currentUser: any = null

vi.mock('@/hooks/useAuthQueries', () => {
  return {
    useCurrentUserQuery: () => ({ data: currentUser }),
  }
})

vi.mock('@/hooks/useCodesQueries', () => {
  return {
    useUsersQuery: () => ({ data: [], isLoading: false, isError: false, error: null }),
  }
})

vi.mock('@/hooks/useRulesQueries', () => {
  return {
    useEntitiesQuery: () => ({ data: [], isLoading: false, isError: false, error: null }),
    useSyncEntitiesMutation: () => ({ mutate: vi.fn(), isPending: false }),
  }
})

vi.mock('@/hooks/useZwavejs', () => {
  return {
    useSyncZwavejsEntitiesMutation: () => ({ mutate: vi.fn(), isPending: false }),
  }
})

vi.mock('@/hooks/useDoorCodesQueries', () => {
  return {
    useDoorCodesQuery: () => ({ data: [], isLoading: false, isError: false, error: null }),
    useCreateDoorCodeMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useUpdateDoorCodeMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useDeleteDoorCodeMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
    useSyncLockConfigMutation: () => ({ isPending: false, mutateAsync: vi.fn() }),
  }
})

vi.mock('@/features/doorCodes/components/DoorCodeCard', () => {
  return { DoorCodeCard: () => <div>DoorCodeCard</div> }
})
vi.mock('@/features/doorCodes/components/DoorCodeCreateCard', () => {
  return { DoorCodeCreateCard: () => <div>DoorCodeCreateCard</div> }
})
vi.mock('@/features/doorCodes/components/DoorCodesOwnerSelector', () => {
  return { DoorCodesOwnerSelector: () => <div>DoorCodesOwnerSelector</div> }
})
vi.mock('@/features/doorCodes/components/LockConfigSyncCard', () => {
  return { LockConfigSyncCard: () => <div>LockConfigSyncCard</div> }
})

describe('DoorCodesPage', () => {
  beforeEach(() => {
    currentUser = { id: 'u1', role: UserRole.USER, displayName: 'User', email: 'u@example.com' }
  })

  it('shows non-admin copy for regular users', () => {
    renderWithProviders(<DoorCodesPage />)
    expect(screen.getByText(/your door codes/i)).toBeInTheDocument()
  })

  it('shows admin management section for admins', () => {
    currentUser = { id: 'a1', role: UserRole.ADMIN, displayName: 'Admin', email: 'a@example.com' }
    renderWithProviders(<DoorCodesPage />)
    expect(screen.getByText(/manage door codes/i)).toBeInTheDocument()
    expect(screen.getByText('DoorCodesOwnerSelector')).toBeInTheDocument()
    expect(screen.getByText('DoorCodeCreateCard')).toBeInTheDocument()
    expect(screen.getByText(/sync codes from lock/i)).toBeInTheDocument()
  })
})

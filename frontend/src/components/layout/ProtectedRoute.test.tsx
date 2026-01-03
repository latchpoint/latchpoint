import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './ProtectedRoute'
import { UserRole } from '@/lib/constants'

let authState: any

vi.mock('@/hooks/useAuth', () => {
  return {
    useAuth: () => authState,
  }
})

describe('ProtectedRoute', () => {
  beforeEach(() => {
    authState = { isAuthenticated: false, user: null, isLoading: false }
  })

  it('renders spinner while loading', () => {
    authState = { isAuthenticated: false, user: null, isLoading: true }
    render(
      <MemoryRouter initialEntries={['/private']}>
        <Routes>
          <Route
            path="/private"
            element={
              <ProtectedRoute>
                <div>Private</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument()
  })

  it('redirects to login when unauthenticated', async () => {
    authState = { isAuthenticated: false, user: null, isLoading: false }
    render(
      <MemoryRouter initialEntries={['/private']}>
        <Routes>
          <Route path="/login" element={<div>Login</div>} />
          <Route
            path="/private"
            element={
              <ProtectedRoute>
                <div>Private</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    )

    expect(await screen.findByText('Login')).toBeInTheDocument()
  })

  it('shows access denied when role is not allowed', () => {
    authState = { isAuthenticated: true, user: { role: UserRole.GUEST }, isLoading: false }
    render(
      <MemoryRouter initialEntries={['/admin']}>
        <Routes>
          <Route
            path="/admin"
            element={
              <ProtectedRoute requiredRoles={[UserRole.ADMIN]}>
                <div>Admin</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByText(/access denied/i)).toBeInTheDocument()
    expect(screen.queryByText('Admin')).toBeNull()
  })
})

import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes as RouterRoutes, Route, Outlet } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/msw/server'
import { Routes, UserRole } from '@/lib/constants'
import { renderWithProviders } from '@/test/render'
import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { SetupGate } from '@/components/layout/SetupGate'

function mockCurrentUser(role: string = UserRole.ADMIN) {
  return {
    id: 'user-1',
    email: 'admin@example.com',
    displayName: 'Admin',
    role,
    isActive: true,
    has2FA: false,
    createdAt: '2026-01-01T00:00:00Z',
    lastLogin: null,
  }
}

function mockSetupStatus(setupRequired: boolean) {
  return {
    onboardingRequired: false,
    setupRequired,
    requirements: {
      hasActiveSettingsProfile: true,
      hasAlarmSnapshot: true,
      hasAlarmCode: !setupRequired,
      hasSensors: true,
      homeAssistantConnected: false,
    },
  }
}

describe('SetupGate + ProtectedRoute', () => {
  it('redirects authenticated users to setup when setup is required', async () => {
    server.use(
      http.get('/api/users/me/', () => HttpResponse.json({ data: mockCurrentUser() })),
      http.get('/api/onboarding/setup-status/', () =>
        HttpResponse.json({ data: mockSetupStatus(true) })
      )
    )

    renderWithProviders(
      <RouterRoutes>
        <Route
          element={
            <ProtectedRoute>
              <SetupGate>
                <Outlet />
              </SetupGate>
            </ProtectedRoute>
          }
        >
          <Route path={Routes.EVENTS} element={<div>Events</div>} />
          <Route path={Routes.SETUP} element={<div>Setup</div>} />
          <Route path={Routes.HOME} element={<div>Home</div>} />
        </Route>
        <Route path={Routes.LOGIN} element={<div>Login</div>} />
      </RouterRoutes>,
      { route: Routes.EVENTS }
    )

    expect(await screen.findByText('Setup')).toBeInTheDocument()
    expect(screen.queryByText('Events')).not.toBeInTheDocument()
  })

  it('redirects away from /setup when setup is not required', async () => {
    server.use(
      http.get('/api/users/me/', () => HttpResponse.json({ data: mockCurrentUser() })),
      http.get('/api/onboarding/setup-status/', () =>
        HttpResponse.json({ data: mockSetupStatus(false) })
      )
    )

    renderWithProviders(
      <RouterRoutes>
        <Route
          element={
            <ProtectedRoute>
              <SetupGate>
                <Outlet />
              </SetupGate>
            </ProtectedRoute>
          }
        >
          <Route path={Routes.SETUP} element={<div>Setup</div>} />
          <Route path={Routes.HOME} element={<div>Home</div>} />
        </Route>
        <Route path={Routes.LOGIN} element={<div>Login</div>} />
      </RouterRoutes>,
      { route: Routes.SETUP }
    )

    expect(await screen.findByText('Home')).toBeInTheDocument()
    expect(screen.queryByText('Setup')).not.toBeInTheDocument()
  })

  it('redirects unauthenticated users to login', async () => {
    server.use(
      http.get('/api/users/me/', () => HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 }))
    )

    renderWithProviders(
      <RouterRoutes>
        <Route element={<ProtectedRoute><Outlet /></ProtectedRoute>}>
          <Route path="/private" element={<div>Private</div>} />
        </Route>
        <Route path={Routes.LOGIN} element={<div>Login</div>} />
      </RouterRoutes>,
      { route: '/private' }
    )

    expect(await screen.findByText('Login')).toBeInTheDocument()
    expect(screen.queryByText('Private')).not.toBeInTheDocument()
  })

  it('shows Access Denied when role requirements fail', async () => {
    server.use(http.get('/api/users/me/', () => HttpResponse.json({ data: mockCurrentUser(UserRole.RESIDENT) })))

    renderWithProviders(
      <RouterRoutes>
        <Route
          element={
            <ProtectedRoute requiredRoles={[UserRole.ADMIN]}>
              <Outlet />
            </ProtectedRoute>
          }
        >
          <Route path="/admin-only" element={<div>Admin Only</div>} />
        </Route>
        <Route path={Routes.LOGIN} element={<div>Login</div>} />
      </RouterRoutes>,
      { route: '/admin-only' }
    )

    expect(await screen.findByText(/access denied/i)).toBeInTheDocument()
    expect(screen.queryByText('Admin Only')).not.toBeInTheDocument()
  })
})


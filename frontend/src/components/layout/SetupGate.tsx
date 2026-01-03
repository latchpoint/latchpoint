import { Navigate, useLocation } from 'react-router-dom'
import { Routes } from '@/lib/constants'
import { Spinner } from '@/components/ui/spinner'
import { useAuthSessionQuery } from '@/hooks/useAuthQueries'
import { useSetupStatusQuery } from '@/hooks/useOnboardingQueries'

interface SetupGateProps {
  children: React.ReactNode
}

export function SetupGate({ children }: SetupGateProps) {
  const location = useLocation()
  const sessionQuery = useAuthSessionQuery()
  const isAuthenticated = sessionQuery.data.isAuthenticated
  const setupStatusQuery = useSetupStatusQuery()
  const status = setupStatusQuery.data ?? null
  const isLoading = setupStatusQuery.isLoading

  if (!isAuthenticated) return <>{children}</>

  if (isLoading && !status) {
    return <Spinner fullscreen size="lg" />
  }

  if (status?.setupRequired) {
    if (!location.pathname.startsWith(Routes.SETUP)) {
      return <Navigate to={Routes.SETUP} replace />
    }
  } else if (location.pathname === Routes.SETUP) {
    return <Navigate to={Routes.HOME} replace />
  }

  return <>{children}</>
}

export default SetupGate

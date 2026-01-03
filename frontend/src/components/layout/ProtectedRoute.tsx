import { Navigate, useLocation } from 'react-router-dom'
import { Routes } from '@/lib/constants'
import { Spinner } from '@/components/ui/spinner'
import { useAuth } from '@/hooks/useAuth'

interface ProtectedRouteProps {
  children: React.ReactNode
  requiredRoles?: string[]
}

export function ProtectedRoute({ children, requiredRoles }: ProtectedRouteProps) {
  const { isAuthenticated, user, isLoading } = useAuth()
  const location = useLocation()

  // Show loading state while checking auth
  if (isLoading) {
    return <Spinner fullscreen size="lg" />
  }

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    return <Navigate to={Routes.LOGIN} state={{ from: location }} replace />
  }

  // Check role requirements if specified
  if (requiredRoles && user && !requiredRoles.includes(user.role)) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-2">Access Denied</h1>
          <p className="text-muted-foreground">
            You don't have permission to access this page.
          </p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}

export default ProtectedRoute

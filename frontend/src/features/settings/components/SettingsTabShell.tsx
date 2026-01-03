import type { ReactNode } from 'react'

import { Alert, AlertDescription } from '@/components/ui/alert'

type Props = {
  isAdmin: boolean
  adminMessage?: string
  showAdminBanner?: boolean
  loadError?: string | null
  error?: string | null
  notice?: string | null
  children: ReactNode
}

export function SettingsTabShell({
  isAdmin,
  adminMessage = 'Admin role required to change settings.',
  showAdminBanner = true,
  loadError,
  error,
  notice,
  children,
}: Props) {
  return (
    <div className="space-y-4">
      {!isAdmin && showAdminBanner ? (
        <Alert>
          <AlertDescription>{adminMessage}</AlertDescription>
        </Alert>
      ) : null}

      {loadError ? (
        <Alert variant="error">
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      ) : null}

      {error ? (
        <Alert variant="error">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : notice ? (
        <Alert>
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      ) : null}

      {children}
    </div>
  )
}

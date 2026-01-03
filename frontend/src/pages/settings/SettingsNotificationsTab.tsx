import { SettingsTabShell } from '@/features/settings/components/SettingsTabShell'
import { NotificationProvidersCard } from '@/features/notifications/components/NotificationProvidersCard'
import { useCurrentUserQuery } from '@/hooks/useAuthQueries'
import { UserRole } from '@/lib/constants'

export function SettingsNotificationsTab() {
  const currentUserQuery = useCurrentUserQuery()
  const isAdmin = currentUserQuery.data?.role === UserRole.ADMIN

  return (
    <SettingsTabShell isAdmin={isAdmin}>
      <NotificationProvidersCard isAdmin={isAdmin} />
    </SettingsTabShell>
  )
}

export default SettingsNotificationsTab

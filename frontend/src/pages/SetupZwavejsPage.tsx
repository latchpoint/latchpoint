import { useNavigate } from 'react-router-dom'
import { Routes } from '@/lib/constants'
import { SetupZwavejsCard } from '@/features/setupZwavejs/components/SetupZwavejsCard'
import { useSetupZwavejsModel } from '@/features/setupZwavejs/hooks/useSetupZwavejsModel'

export function SetupZwavejsPage() {
  const navigate = useNavigate()
  const model = useSetupZwavejsModel()

  return (
    <SetupZwavejsCard
      isAdmin={model.isAdmin}
      error={model.error}
      notice={model.notice}
      isBusy={model.isSubmitting || model.syncEntities.isPending}
      isSyncing={model.syncEntities.isPending}
      connected={model.statusQuery.data?.connected}
      integrationEnabled={model.statusQuery.data?.enabled}
      lastError={model.statusQuery.data?.lastError || undefined}
      watch={model.watch}
      onSync={model.onSync}
      onBackToSettings={() => navigate(Routes.SETTINGS, { replace: true })}
    />
  )
}

export default SetupZwavejsPage

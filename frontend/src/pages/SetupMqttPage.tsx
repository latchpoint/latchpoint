import { useNavigate } from 'react-router-dom'
import { Routes } from '@/lib/constants'
import { SetupMqttCard } from '@/features/setupMqtt/components/SetupMqttCard'
import { useSetupMqttModel } from '@/features/setupMqtt/hooks/useSetupMqttModel'

export function SetupMqttPage() {
  const navigate = useNavigate()
  const model = useSetupMqttModel()

  return (
    <SetupMqttCard
      isAdmin={model.isAdmin}
      error={model.error}
      notice={model.notice}
      connected={model.statusQuery.data?.connected}
      lastError={model.statusQuery.data?.lastError || undefined}
      hasSavedPassword={Boolean(model.settingsQuery.data?.hasPassword)}
      watch={model.watch}
      onBackToSettings={() => navigate(Routes.SETTINGS, { replace: true })}
    />
  )
}

export default SetupMqttPage

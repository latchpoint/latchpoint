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
      isBusy={model.isSubmitting}
      isSubmitting={model.isSubmitting}
      isTesting={false}
      formErrors={model.errors}
      register={model.register}
      handleSubmit={model.handleSubmit}
      watch={model.watch}
      setValue={model.setValue}
      onBackToSettings={() => navigate(Routes.SETTINGS, { replace: true })}
    />
  )
}

export default SetupMqttPage

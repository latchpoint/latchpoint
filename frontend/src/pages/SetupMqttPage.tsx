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
      passwordFieldValue={String(model.watch('password') || '')}
      isBusy={model.isSubmitting || model.updateSettings.isPending}
      isSubmitting={model.isSubmitting}
      isTesting={model.testConnection.isPending}
      formErrors={model.errors}
      register={model.register}
      handleSubmit={model.handleSubmit}
      watch={model.watch}
      setValue={model.setValue}
      onSubmit={model.onSubmit}
      onTest={model.onTest}
      onClearPassword={model.onClearPassword}
      onBackToSettings={() => navigate(Routes.SETTINGS, { replace: true })}
    />
  )
}

export default SetupMqttPage

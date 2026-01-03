import { useNavigate } from 'react-router-dom'
import { Routes } from '@/lib/constants'
import { SetupWizardCard } from '@/features/setupWizard/components/SetupWizardCard'
import { useSetupWizardModel } from '@/features/setupWizard/hooks/useSetupWizardModel'

export function SetupWizardPage() {
  const navigate = useNavigate()
  const model = useSetupWizardModel({ onSuccess: () => navigate(Routes.SETUP_MQTT, { replace: true }) })

  return (
    <SetupWizardCard
      isAdmin={model.isAdmin}
      error={model.error}
      allowedStates={model.allowedStates}
      armableStates={model.armableStates}
      setAllowedStates={model.setAllowedStates}
      register={model.register}
      handleSubmit={model.handleSubmit}
      formErrors={model.formErrors}
      isSubmitting={model.isSubmitting}
      onSubmit={model.onSubmit}
      onLogout={() => model.logout()}
    />
  )
}

export default SetupWizardPage

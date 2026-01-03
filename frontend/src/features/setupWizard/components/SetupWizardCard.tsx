import { ShieldCheck } from 'lucide-react'
import type { AlarmStateType } from '@/lib/constants'
import type { FieldErrors, UseFormHandleSubmit, UseFormRegister } from 'react-hook-form'
import { AdminActionRequiredAlert } from '@/features/settings/components/AdminActionRequiredAlert'
import { AllowedArmStatesPicker } from '@/features/codes/components/AllowedArmStatesPicker'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { CenteredCard } from '@/components/ui/centered-card'
import { FormField } from '@/components/ui/form-field'
import type { SetupWizardFormData } from '@/features/setupWizard/hooks/useSetupWizardModel'

type Props = {
  isAdmin: boolean
  error: string | null
  allowedStates: AlarmStateType[]
  armableStates: AlarmStateType[]
  setAllowedStates: (next: AlarmStateType[]) => void
  register: UseFormRegister<SetupWizardFormData>
  handleSubmit: UseFormHandleSubmit<SetupWizardFormData>
  formErrors: FieldErrors<SetupWizardFormData>
  isSubmitting: boolean
  onSubmit: (data: SetupWizardFormData) => Promise<void>
  onLogout: () => void
}

export function SetupWizardCard({
  isAdmin,
  error,
  allowedStates,
  armableStates,
  setAllowedStates,
  register,
  handleSubmit,
  formErrors,
  isSubmitting,
  onSubmit,
  onLogout,
}: Props) {
  return (
    <CenteredCard
      layout="section"
      title="Create an Alarm Code"
      description="You need at least one code to arm and disarm."
      icon={<ShieldCheck className="h-6 w-6" />}
    >
      {!isAdmin ? (
        <div className="space-y-4">
          <AdminActionRequiredAlert layout="banner" description="An admin must create your alarm code before you can use the system." />
          <Button type="button" className="w-full" variant="secondary" onClick={onLogout}>
            Log out
          </Button>
        </div>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <FormField label="Label (optional)" htmlFor="label" error={formErrors.label?.message}>
            <Input id="label" type="text" placeholder="Admin" {...register('label')} disabled={isSubmitting} />
          </FormField>

          <FormField label="Code" htmlFor="code" required error={formErrors.code?.message}>
            <Input
              id="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="4–8 digits"
              {...register('code')}
              disabled={isSubmitting}
            />
          </FormField>

          <div className="space-y-2">
            <AllowedArmStatesPicker states={armableStates} value={allowedStates} onChange={setAllowedStates} disabled={isSubmitting} />
          </div>

          <FormField label="Re-authenticate (password)" htmlFor="reauthPassword" required error={formErrors.reauthPassword?.message}>
            <Input id="reauthPassword" type="password" placeholder="Your account password" {...register('reauthPassword')} disabled={isSubmitting} />
          </FormField>

          {error ? (
            <Alert variant="error" layout="inline">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? 'Saving…' : 'Save Code'}
          </Button>
        </form>
      )}
    </CenteredCard>
  )
}


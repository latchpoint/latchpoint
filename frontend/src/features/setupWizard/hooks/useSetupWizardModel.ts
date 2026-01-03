import { useMemo, useState } from 'react'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useQueryClient } from '@tanstack/react-query'
import { AlarmState, UserRole } from '@/lib/constants'
import type { AlarmStateType } from '@/lib/constants'
import { getErrorMessage } from '@/lib/errors'
import { codesService } from '@/services'
import { useAuth } from '@/hooks/useAuth'
import { queryKeys } from '@/types'

const ARMABLE_STATES: AlarmStateType[] = [
  AlarmState.ARMED_HOME,
  AlarmState.ARMED_AWAY,
  AlarmState.ARMED_NIGHT,
  AlarmState.ARMED_VACATION,
  AlarmState.ARMED_CUSTOM_BYPASS,
]

const schema = z.object({
  label: z.string().max(150).optional(),
  code: z
    .string()
    .regex(/^\\d+$/, 'Code must be digits only')
    .min(4, 'Code must be 4–8 digits')
    .max(8, 'Code must be 4–8 digits'),
  reauthPassword: z.string().min(1, 'Password is required'),
})

export type SetupWizardFormData = z.infer<typeof schema>

export function useSetupWizardModel(opts: { onSuccess: () => void }) {
  const queryClient = useQueryClient()
  const { user, logout } = useAuth()
  const isAdmin = user?.role === UserRole.ADMIN
  const [error, setError] = useState<string | null>(null)
  const [allowedStates, setAllowedStates] = useState<AlarmStateType[]>(ARMABLE_STATES)

  const defaultValues = useMemo<SetupWizardFormData>(() => ({ label: 'Admin', code: '', reauthPassword: '' }), [])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SetupWizardFormData>({ resolver: zodResolver(schema), defaultValues })

  const onSubmit = async (data: SetupWizardFormData) => {
    setError(null)
    try {
      if (!user) {
        setError('Not authenticated.')
        return
      }
      if (user.role !== UserRole.ADMIN) {
        setError('An admin must create your alarm code.')
        return
      }

      await codesService.createCode({
        userId: user.id,
        code: data.code,
        label: data.label || '',
        allowedStates,
        reauthPassword: data.reauthPassword,
      })
      await queryClient.invalidateQueries({ queryKey: queryKeys.onboarding.setupStatus })
      opts.onSuccess()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to create code')
    }
  }

  return {
    user,
    logout,
    isAdmin,
    error,
    allowedStates,
    setAllowedStates,
    register,
    handleSubmit,
    formErrors: errors,
    isSubmitting,
    onSubmit,
    armableStates: ARMABLE_STATES,
  }
}


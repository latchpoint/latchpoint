import { useEffect, useMemo } from 'react'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { UserRole } from '@/lib/constants'
import { useAuth } from '@/hooks/useAuth'
import {
  useMqttSettingsQuery,
  useMqttStatusQuery,
} from '@/hooks/useMqtt'

const schema = z.object({
  enabled: z.boolean(),
  host: z.string().trim().optional(),
  port: z.string().min(1, 'Port is required'),
  username: z.string().optional(),
  useTls: z.boolean(),
  tlsInsecure: z.boolean(),
  clientId: z.string().optional(),
  keepaliveSeconds: z.string().min(1, 'Keepalive is required'),
  connectTimeoutSeconds: z.string().min(1, 'Connect timeout is required'),
})

export type SetupMqttFormData = z.infer<typeof schema>

export function useSetupMqttModel() {
  const { user } = useAuth()
  const isAdmin = user?.role === UserRole.ADMIN

  const statusQuery = useMqttStatusQuery()
  const settingsQuery = useMqttSettingsQuery()

  const initialValues = useMemo<SetupMqttFormData | null>(() => {
    if (!settingsQuery.data) return null
    return {
      enabled: settingsQuery.data.enabled,
      host: settingsQuery.data.host || '',
      port: String(settingsQuery.data.port ?? 1883),
      username: settingsQuery.data.username || '',
      useTls: settingsQuery.data.useTls,
      tlsInsecure: settingsQuery.data.tlsInsecure,
      clientId: settingsQuery.data.clientId || 'latchpoint-alarm',
      keepaliveSeconds: String(settingsQuery.data.keepaliveSeconds ?? 30),
      connectTimeoutSeconds: String(settingsQuery.data.connectTimeoutSeconds ?? 5),
    }
  }, [settingsQuery.data])

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<SetupMqttFormData>({
    resolver: zodResolver(schema),
    defaultValues: initialValues ?? undefined,
  })

  useEffect(() => {
    if (!initialValues) return
    reset(initialValues)
  }, [initialValues, reset])

  const enabled = watch('enabled')

  return {
    isAdmin,
    error: null as string | null,
    notice: null as string | null,
    statusQuery,
    settingsQuery,
    enabled,
    register,
    handleSubmit,
    setValue,
    watch,
    errors,
    isSubmitting,
  }
}

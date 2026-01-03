import { useEffect, useMemo, useState } from 'react'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { UserRole } from '@/lib/constants'
import { getErrorMessage } from '@/lib/errors'
import { parseFloatInRange, parseIntInRange } from '@/lib/numberParsers'
import { useAuth } from '@/hooks/useAuth'
import {
  useMqttSettingsQuery,
  useMqttStatusQuery,
  useTestMqttConnectionMutation,
  useUpdateMqttSettingsMutation,
} from '@/hooks/useMqtt'

const schema = z.object({
  enabled: z.boolean(),
  host: z.string().trim().optional(),
  port: z.string().min(1, 'Port is required'),
  username: z.string().optional(),
  password: z.string().optional(),
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
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const statusQuery = useMqttStatusQuery()
  const settingsQuery = useMqttSettingsQuery()

  const updateSettings = useUpdateMqttSettingsMutation()
  const testConnection = useTestMqttConnectionMutation()

  const initialValues = useMemo<SetupMqttFormData | null>(() => {
    if (!settingsQuery.data) return null
    return {
      enabled: settingsQuery.data.enabled,
      host: settingsQuery.data.host || '',
      port: String(settingsQuery.data.port ?? 1883),
      username: settingsQuery.data.username || '',
      password: '',
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

  const save = async (data: SetupMqttFormData) => {
    setError(null)
    setNotice(null)
    if (!isAdmin) {
      setError('Admin role required to configure MQTT.')
      return
    }
    try {
      const port = parseIntInRange('Port', data.port, 1, 65535)
      const keepaliveSeconds = parseIntInRange('Keepalive', data.keepaliveSeconds, 5, 3600)
      const connectTimeoutSeconds = parseFloatInRange('Connect timeout', data.connectTimeoutSeconds, 0.5, 30)
      await updateSettings.mutateAsync({
        enabled: data.enabled,
        host: data.host?.trim() || '',
        port,
        username: data.username?.trim() || '',
        ...(data.password?.trim() ? { password: data.password } : {}),
        useTls: data.useTls,
        tlsInsecure: data.tlsInsecure,
        clientId: data.clientId?.trim() || 'latchpoint-alarm',
        keepaliveSeconds,
        connectTimeoutSeconds,
      })
      setValue('password', '')
      setNotice('Saved MQTT settings.')
      void statusQuery.refetch()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save MQTT settings')
    }
  }

  const test = async () => {
    setError(null)
    setNotice(null)
    const data = watch()
    try {
      const port = parseIntInRange('Port', data.port, 1, 65535)
      const keepaliveSeconds = parseIntInRange('Keepalive', data.keepaliveSeconds, 5, 3600)
      const connectTimeoutSeconds = parseFloatInRange('Connect timeout', data.connectTimeoutSeconds, 0.5, 30)
      await testConnection.mutateAsync({
        host: data.host?.trim() || '',
        port,
        username: data.username?.trim() || '',
        password: data.password?.trim() || undefined,
        useTls: data.useTls,
        tlsInsecure: data.tlsInsecure,
        clientId: data.clientId?.trim() || 'latchpoint-alarm',
        keepaliveSeconds,
        connectTimeoutSeconds,
      })
      setNotice('Connection OK.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Connection failed')
    }
  }

  const clearPassword = async () => {
    setError(null)
    setNotice(null)
    try {
      await updateSettings.mutateAsync({ password: '' })
      setValue('password', '')
      setNotice('Cleared MQTT password.')
      void statusQuery.refetch()
      void settingsQuery.refetch()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to clear MQTT password')
    }
  }

  return {
    isAdmin,
    error,
    notice,
    statusQuery,
    settingsQuery,
    updateSettings,
    testConnection,
    enabled,
    register,
    handleSubmit,
    setValue,
    watch,
    errors,
    isSubmitting,
    onSubmit: save,
    onTest: test,
    onClearPassword: clearPassword,
  }
}


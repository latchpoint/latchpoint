import { useEffect, useMemo, useState } from 'react'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { UserRole } from '@/lib/constants'
import { getErrorMessage } from '@/lib/errors'
import { parseFloatInRange, parseIntInRange } from '@/lib/numberParsers'
import { useAuth } from '@/hooks/useAuth'
import {
  useSyncZwavejsEntitiesMutation,
  useTestZwavejsConnectionMutation,
  useUpdateZwavejsSettingsMutation,
  useZwavejsSettingsQuery,
  useZwavejsStatusQuery,
} from '@/hooks/useZwavejs'

const schema = z.object({
  enabled: z.boolean(),
  wsUrl: z
    .string()
    .trim()
    .min(1, 'WebSocket URL is required')
    .refine((value) => value.startsWith('ws://') || value.startsWith('wss://'), 'Must start with ws:// or wss://'),
  connectTimeoutSeconds: z.string().min(1, 'Connect timeout is required'),
  reconnectMinSeconds: z.string().min(1, 'Reconnect min is required'),
  reconnectMaxSeconds: z.string().min(1, 'Reconnect max is required'),
})

export type SetupZwavejsFormData = z.infer<typeof schema>

export function useSetupZwavejsModel() {
  const { user } = useAuth()
  const isAdmin = user?.role === UserRole.ADMIN
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const statusQuery = useZwavejsStatusQuery()
  const settingsQuery = useZwavejsSettingsQuery()
  const updateSettings = useUpdateZwavejsSettingsMutation()
  const testConnection = useTestZwavejsConnectionMutation()
  const syncEntities = useSyncZwavejsEntitiesMutation()

  const initialValues = useMemo<SetupZwavejsFormData | null>(() => {
    if (!settingsQuery.data) return null
    return {
      enabled: settingsQuery.data.enabled,
      wsUrl: settingsQuery.data.wsUrl || '',
      connectTimeoutSeconds: String(settingsQuery.data.connectTimeoutSeconds ?? 5),
      reconnectMinSeconds: String(settingsQuery.data.reconnectMinSeconds ?? 1),
      reconnectMaxSeconds: String(settingsQuery.data.reconnectMaxSeconds ?? 30),
    }
  }, [settingsQuery.data])

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<SetupZwavejsFormData>({
    resolver: zodResolver(schema),
    defaultValues: initialValues ?? undefined,
  })

  useEffect(() => {
    if (!initialValues) return
    reset(initialValues)
  }, [initialValues, reset])

  const enabled = watch('enabled')

  const save = async (data: SetupZwavejsFormData) => {
    setError(null)
    setNotice(null)
    if (!isAdmin) {
      setError('Admin role required to configure Z-Wave JS.')
      return
    }

    try {
      const connectTimeoutSeconds = parseFloatInRange('Connect timeout', data.connectTimeoutSeconds, 0.5, 30)
      const reconnectMinSeconds = parseIntInRange('Reconnect min', data.reconnectMinSeconds, 0, 300)
      const reconnectMaxSeconds = parseIntInRange('Reconnect max', data.reconnectMaxSeconds, 0, 300)
      if (reconnectMaxSeconds && reconnectMinSeconds && reconnectMaxSeconds < reconnectMinSeconds) {
        throw new Error('Reconnect max must be >= reconnect min.')
      }

      await updateSettings.mutateAsync({
        enabled: data.enabled,
        wsUrl: data.wsUrl.trim(),
        connectTimeoutSeconds,
        reconnectMinSeconds,
        reconnectMaxSeconds,
      })
      setNotice('Saved Z-Wave JS settings.')
      void statusQuery.refetch()
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save Z-Wave JS settings')
    }
  }

  const test = async () => {
    setError(null)
    setNotice(null)
    const data = watch()
    try {
      const connectTimeoutSeconds = parseFloatInRange('Connect timeout', data.connectTimeoutSeconds, 0.5, 30)
      await testConnection.mutateAsync({
        wsUrl: data.wsUrl.trim(),
        connectTimeoutSeconds,
      })
      setNotice('Connection OK.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Connection failed')
    }
  }

  const sync = async () => {
    setError(null)
    setNotice(null)
    try {
      const res = await syncEntities.mutateAsync()
      setNotice(res.notice)
    } catch (err) {
      setError(getErrorMessage(err) || 'Entity sync failed')
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
    syncEntities,
    enabled,
    register,
    handleSubmit,
    setValue,
    watch,
    errors,
    isSubmitting,
    onSubmit: save,
    onTest: test,
    onSync: sync,
  }
}


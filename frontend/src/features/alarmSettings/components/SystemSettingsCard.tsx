import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { SectionCard } from '@/components/ui/section-card'
import { useBatchUpdateSystemConfigMutation, useSystemConfigQuery } from '@/hooks/useSettingsQueries'
import { getErrorMessage } from '@/types/errors'

type Props = {
  isAdmin: boolean
}

export type IntegerSetting = {
  key: string
  defaultValue: number
  min: number
  max: number
}

export const SYSTEM_SETTINGS: IntegerSetting[] = [
  {
    key: 'events.retention_days',
    defaultValue: 30,
    min: 0,
    max: 3650,
  },
  {
    key: 'notification_logs.retention_days',
    defaultValue: 30,
    min: 0,
    max: 3650,
  },
  {
    key: 'notification_deliveries.retention_days',
    defaultValue: 30,
    min: 0,
    max: 3650,
  },
  {
    key: 'door_code_events.retention_days',
    defaultValue: 90,
    min: 0,
    max: 3650,
  },
]

export function SystemSettingsCard({ isAdmin }: Props) {
  const systemConfigQuery = useSystemConfigQuery()
  const updateMutation = useBatchUpdateSystemConfigMutation()

  const [localValues, setLocalValues] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const getCurrentValue = (key: string, defaultValue: number): number => {
    const row = systemConfigQuery.data?.find((c) => c.key === key)
    const value = row?.value
    return typeof value === 'number' ? value : defaultValue
  }

  const hasChanges = SYSTEM_SETTINGS.some((s) => {
    const current = getCurrentValue(s.key, s.defaultValue)
    const local = localValues[s.key]
    return local !== undefined && local !== String(current)
  })

  const handleSave = async () => {
    setError(null)
    setNotice(null)

    const changes = SYSTEM_SETTINGS.flatMap((s) => {
      const current = getCurrentValue(s.key, s.defaultValue)
      const local = localValues[s.key]
      if (local === undefined || local === String(current)) return []
      return [{ setting: s, raw: local }]
    })
    if (changes.length === 0) return

    for (const { setting, raw } of changes) {
      const parsed = parseInt(raw, 10)
      if (isNaN(parsed) || parsed < setting.min || parsed > setting.max) {
        const name = systemConfigQuery.data?.find((c) => c.key === setting.key)?.name ?? setting.key
        setError(`${name} must be between ${setting.min} and ${setting.max}`)
        return
      }
    }

    try {
      await updateMutation.mutateAsync(
        changes.map(({ setting, raw }) => ({
          key: setting.key,
          changes: { value: parseInt(raw, 10) },
        })),
      )
      setLocalValues({})
      setNotice('Saved system settings.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save system settings')
    }
  }

  const handleReset = () => {
    setLocalValues({})
    setError(null)
    setNotice(null)
  }

  if (!isAdmin) return null

  return (
    <SectionCard
      title="System"
      description="System-level configuration."
      actions={
        hasChanges ? (
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleReset} disabled={updateMutation.isPending}>
              Reset
            </Button>
            <Button size="sm" onClick={handleSave} disabled={updateMutation.isPending}>
              Save
            </Button>
          </div>
        ) : null
      }
    >
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}
      {notice && <p className="mb-4 text-sm text-muted-foreground">{notice}</p>}

      <div className="grid gap-4 md:grid-cols-2">
        {SYSTEM_SETTINGS.map((s) => {
          const currentValue = getCurrentValue(s.key, s.defaultValue)
          const displayValue = localValues[s.key] ?? String(currentValue)
          const row = systemConfigQuery.data?.find((c) => c.key === s.key)
          const label = row?.name ?? s.key
          const help = row?.description ?? ''
          const inputId = `system-setting-${s.key}`

          return (
            <FormField key={s.key} label={label} help={help} htmlFor={inputId}>
              <Input
                id={inputId}
                type="number"
                min={s.min}
                max={s.max}
                value={displayValue}
                onChange={(e) => setLocalValues((prev) => ({ ...prev, [s.key]: e.target.value }))}
                disabled={!isAdmin || updateMutation.isPending || systemConfigQuery.isLoading}
              />
            </FormField>
          )
        })}
      </div>
    </SectionCard>
  )
}

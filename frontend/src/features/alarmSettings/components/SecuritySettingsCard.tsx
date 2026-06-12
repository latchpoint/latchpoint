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

// Alarm-code rate limiting + failed-attempt lockout. Defaults and the `0 = disabled`
// convention mirror the backend `alarm_code.*` SystemConfig registry entries.
// eslint-disable-next-line react-refresh/only-export-components
export const SECURITY_SETTINGS: IntegerSetting[] = [
  {
    key: 'alarm_code.rate_limit_max_attempts',
    defaultValue: 10,
    min: 0,
    max: 1000,
  },
  {
    key: 'alarm_code.rate_limit_window_seconds',
    defaultValue: 60,
    min: 1,
    max: 3600,
  },
  {
    key: 'alarm_code.lockout_threshold',
    defaultValue: 5,
    min: 0,
    max: 1000,
  },
  {
    key: 'alarm_code.lockout_duration_seconds',
    defaultValue: 300,
    min: 1,
    max: 86400,
  },
]

export function SecuritySettingsCard({ isAdmin }: Props) {
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

  const hasChanges = SECURITY_SETTINGS.some((s) => {
    const current = getCurrentValue(s.key, s.defaultValue)
    const local = localValues[s.key]
    return local !== undefined && local !== String(current)
  })

  const handleSave = async () => {
    setError(null)
    setNotice(null)

    const changes = SECURITY_SETTINGS.flatMap((s) => {
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
      setNotice('Saved alarm code security settings.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save alarm code security settings')
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
      title="Alarm code security"
      description="Rate limiting and failed-attempt lockout for alarm-code entry (web, keypad, MQTT). Set an attempts value to 0 to disable that layer."
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
        {SECURITY_SETTINGS.map((s) => {
          const currentValue = getCurrentValue(s.key, s.defaultValue)
          const displayValue = localValues[s.key] ?? String(currentValue)
          const row = systemConfigQuery.data?.find((c) => c.key === s.key)
          const label = row?.name ?? s.key
          const help = row?.description ?? ''
          const inputId = `security-setting-${s.key}`

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

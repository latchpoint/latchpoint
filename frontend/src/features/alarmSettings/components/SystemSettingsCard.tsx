import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { SectionCard } from '@/components/ui/section-card'
import { useSystemConfigQuery, useUpdateSystemConfigMutation } from '@/hooks/useSettingsQueries'
import { getErrorMessage } from '@/types/errors'

type Props = {
  isAdmin: boolean
}

export function SystemSettingsCard({ isAdmin }: Props) {
  const systemConfigQuery = useSystemConfigQuery()
  const updateMutation = useUpdateSystemConfigMutation()

  const [localRetention, setLocalRetention] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const retentionConfig = systemConfigQuery.data?.find((c) => c.key === 'events.retention_days')
  const currentRetention = retentionConfig?.value ?? 30
  const displayValue = localRetention ?? String(currentRetention)
  const hasChanges = localRetention !== null && localRetention !== String(currentRetention)

  const handleSave = async () => {
    if (!localRetention) return
    setError(null)
    setNotice(null)

    const parsed = parseInt(localRetention, 10)
    if (isNaN(parsed) || parsed < 1 || parsed > 365) {
      setError('Retention must be between 1 and 365 days')
      return
    }

    try {
      await updateMutation.mutateAsync({
        key: 'events.retention_days',
        changes: { value: parsed },
      })
      setLocalRetention(null)
      setNotice('Saved retention setting.')
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to save retention setting')
    }
  }

  const handleReset = () => {
    setLocalRetention(null)
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
        <FormField
          label="Event retention (days)"
          help="Events older than this will be automatically deleted."
        >
          <Input
            type="number"
            min={1}
            max={365}
            value={displayValue}
            onChange={(e) => setLocalRetention(e.target.value)}
            disabled={!isAdmin || updateMutation.isPending || systemConfigQuery.isLoading}
          />
        </FormField>
      </div>
    </SectionCard>
  )
}

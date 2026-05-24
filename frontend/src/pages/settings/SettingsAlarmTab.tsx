import { LoadingInline } from '@/components/ui/loading-inline'
import { SettingsTabShell } from '@/features/settings/components/SettingsTabShell'
import { AlarmArmModesCard } from '@/features/alarmSettings/components/AlarmArmModesCard'
import { SystemSettingsCard } from '@/features/alarmSettings/components/SystemSettingsCard'
import { useAlarmSettingsTabModel } from '@/features/alarmSettings/hooks/useAlarmSettingsTabModel'

export function SettingsAlarmTab() {
  const model = useAlarmSettingsTabModel()

  return (
    <SettingsTabShell isAdmin={model.isAdmin} loadError={model.loadError} error={model.error} notice={model.notice}>
      {model.settingsQuery.isLoading ? (
        <div className="py-6">
          <LoadingInline label="Loading settings…" />
        </div>
      ) : !model.draft ? null : (
        <div className="space-y-6">
          <AlarmArmModesCard
            isAdmin={model.isAdmin}
            isLoading={model.isLoading}
            hasInitialDraft={Boolean(model.initialDraft)}
            draft={model.draft}
            onRefresh={() => void model.settingsQuery.refetch()}
            onReset={model.reset}
            onSave={() => void model.save()}
            onSetDraft={model.setDraft}
          />

          <SystemSettingsCard isAdmin={model.isAdmin} />
        </div>
      )}
    </SettingsTabShell>
  )
}

export default SettingsAlarmTab

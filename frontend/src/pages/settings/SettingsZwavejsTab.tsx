import { SettingsTabShell } from '@/features/settings/components/SettingsTabShell'
import { useZwavejsSettingsModel } from '@/features/zwavejs/hooks/useZwavejsSettingsModel'
import { ZwavejsSettingsCard } from '@/features/zwavejs/components/ZwavejsSettingsCard'

export function SettingsZwavejsTab() {
  const model = useZwavejsSettingsModel()

  return (
    <SettingsTabShell isAdmin={model.isAdmin} error={model.error} notice={model.notice}>
      <ZwavejsSettingsCard
        isAdmin={model.isAdmin}
        isBusy={model.isBusy}
        values={model.draft}
        maskedFlags={model.maskedFlags}
        isLoading={model.settingsQuery.isLoading}
        connected={model.statusQuery.data?.connected}
        enabled={model.statusQuery.data?.enabled}
        lastError={model.statusQuery.data?.lastError ?? undefined}
        saveDisabled={model.saveDisabled}
        onRefresh={model.refresh}
        onSave={() => void model.save()}
        onSync={() => void model.sync()}
        onChange={model.handleFieldChange}
      />
    </SettingsTabShell>
  )
}

export default SettingsZwavejsTab

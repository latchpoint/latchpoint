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
        draft={model.draft}
        isLoading={model.settingsQuery.isLoading}
        connected={model.statusQuery.data?.connected}
        enabled={model.statusQuery.data?.enabled}
        lastError={model.statusQuery.data?.lastError ?? undefined}
        hasInitialDraft={Boolean(model.initialDraft)}
        onRefresh={model.refresh}
        onReset={model.reset}
        onSave={() => void model.save()}
        onTest={() => void model.test()}
        onSync={() => void model.sync()}
        onSetDraft={model.setDraft}
      />
    </SettingsTabShell>
  )
}

export default SettingsZwavejsTab


import { SettingsTabShell } from '@/features/settings/components/SettingsTabShell'
import { useFrigateSettingsModel } from '@/features/frigate/hooks/useFrigateSettingsModel'
import { FrigateOverviewCard } from '@/features/frigate/components/FrigateOverviewCard'
import { FrigateRecentDetectionsCard } from '@/features/frigate/components/FrigateRecentDetectionsCard'
import { FrigateSettingsCard } from '@/features/frigate/components/FrigateSettingsCard'

export function SettingsFrigateTab() {
  const model = useFrigateSettingsModel()
  const status = model.statusQuery.data

  return (
    <SettingsTabShell isAdmin={model.isAdmin} error={model.error} notice={model.notice} adminMessage="Admin role required to edit Frigate settings.">
      <div className="space-y-6 pt-6">
        <FrigateOverviewCard
          isAdmin={model.isAdmin}
          isBusy={model.isBusy}
          mqttReady={model.mqttReady}
          hasDraft={Boolean(model.draft)}
          draftEnabled={model.draft?.enabled ?? false}
          onSetEnabled={(enabled) => model.setDraft((prev) => (prev ? { ...prev, enabled } : prev))}
          onSetError={model.setError}
          onRefresh={model.refresh}
          onReset={model.reset}
          onSave={() => void model.save()}
          mqttConnected={model.mqttConnected}
          available={status?.available}
          ingestLastError={status?.ingest?.lastError}
          ingestLastIngestAt={status?.ingest?.lastIngestAt}
          rulesLastRunAt={status?.rulesRun?.lastRulesRunAt}
          isLoading={model.statusQuery.isLoading}
          error={model.statusQuery.error}
        />

        <FrigateSettingsCard
          isAdmin={model.isAdmin}
          isBusy={model.isBusy}
          draft={model.draft}
          isLoading={model.settingsQuery.isLoading}
          onSetDraft={model.setDraft}
        />

        <FrigateRecentDetectionsCard
          isAdmin={model.isAdmin}
          isLoading={model.detectionsQuery.isLoading}
          isFetching={model.detectionsQuery.isFetching}
          error={model.detectionsQuery.error}
          detections={model.detectionsQuery.data}
          onRefresh={() => void model.detectionsQuery.refetch()}
        />
      </div>
    </SettingsTabShell>
  )
}

export default SettingsFrigateTab

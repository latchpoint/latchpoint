import { SettingsTabShell } from '@/features/settings/components/SettingsTabShell'
import { useFrigateSettingsModel } from '@/features/frigate/hooks/useFrigateSettingsModel'
import { FrigateOverviewCard } from '@/features/frigate/components/FrigateOverviewCard'
import { FrigateRecentDetectionsCard } from '@/features/frigate/components/FrigateRecentDetectionsCard'
import { FrigateSettingsCard } from '@/features/frigate/components/FrigateSettingsCard'

export function SettingsFrigateTab() {
  const model = useFrigateSettingsModel()
  const status = model.statusQuery.data

  return (
    <SettingsTabShell isAdmin={model.isAdmin} error={model.error} notice={model.notice}>
      <div className="space-y-6 pt-6">
        <FrigateOverviewCard
          isAdmin={model.isAdmin}
          isBusy={model.isBusy}
          mqttReady={model.mqttReady}
          enabled={model.settings?.enabled ?? false}
          onRefresh={model.refresh}
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
          settings={model.settings}
          isLoading={model.settingsQuery.isLoading}
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

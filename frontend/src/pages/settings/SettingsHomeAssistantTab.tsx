import { SettingsTabShell } from '@/features/settings/components/SettingsTabShell'
import { useHomeAssistantSettingsModel } from '@/features/homeAssistant/hooks/useHomeAssistantSettingsModel'
import { HomeAssistantConnectionCard } from '@/features/homeAssistant/components/HomeAssistantConnectionCard'
import { HomeAssistantMqttAlarmEntityCard } from '@/features/homeAssistant/components/HomeAssistantMqttAlarmEntityCard'
import { HomeAssistantOverviewCard } from '@/features/homeAssistant/components/HomeAssistantOverviewCard'

export function SettingsHomeAssistantTab() {
  const model = useHomeAssistantSettingsModel()

  return (
    <SettingsTabShell isAdmin={model.isAdmin} error={model.error} notice={model.notice}>
      <div className="space-y-4">
        <HomeAssistantOverviewCard
          isAdmin={model.isAdmin}
          isBusy={model.updateHaSettingsMutation.isPending}
          draft={model.haConnectionDraft}
          reachable={model.haStatusQuery.data?.reachable}
          configured={model.haStatusQuery.data?.configured}
          lastError={model.haStatusQuery.data?.error}
          onRefresh={model.refreshConnection}
          onReset={model.resetConnection}
          onSave={() => void model.saveConnection()}
          onSetDraft={model.setHaConnectionDraft}
        />

        <HomeAssistantConnectionCard
          isAdmin={model.isAdmin}
          draft={model.haConnectionDraft}
          isLoading={model.haSettingsQuery.isLoading}
          isError={model.haSettingsQuery.isError}
          loadError={model.haSettingsQuery.error}
          isPending={model.updateHaSettingsMutation.isPending}
          onClearToken={() => void model.clearToken()}
          onSetDraft={model.setHaConnectionDraft}
        />

        <HomeAssistantMqttAlarmEntityCard
          isAdmin={model.isAdmin}
          mqttReady={model.mqttReady}
          draft={model.haMqttEntityDraft}
          status={model.haMqttEntityStatus}
          isSaving={model.updateHaMqttAlarmEntityMutation.isPending}
          isPublishing={model.publishHaMqttDiscoveryMutation.isPending}
          onSetDraft={model.setHaMqttEntityDraft}
          onSave={() => void model.saveMqttEntity()}
          onPublishDiscovery={() => void model.publishDiscovery()}
          onRefresh={model.refreshMqttEntity}
        />
      </div>
    </SettingsTabShell>
  )
}

export default SettingsHomeAssistantTab

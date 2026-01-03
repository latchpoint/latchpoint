import { SettingsTabShell } from '@/features/settings/components/SettingsTabShell'
import { useZigbee2mqttSettingsModel } from '@/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel'
import { Zigbee2mqttSettingsCard } from '@/features/zigbee2mqtt/components/Zigbee2mqttSettingsCard'

export function SettingsZigbee2mqttTab() {
  const model = useZigbee2mqttSettingsModel()

  return (
    <SettingsTabShell isAdmin={model.isAdmin} showAdminBanner={false} error={model.error} notice={model.notice}>
      <div className="mt-4 space-y-4">
        <Zigbee2mqttSettingsCard
          isAdmin={model.isAdmin}
          isBusy={model.isBusy}
          mqttReady={model.mqttReady}
          mqttConnected={model.mqttConnected}
          z2mEnabled={model.z2mEnabled}
          z2mConnected={model.z2mConnected}
          lastSyncAt={model.lastSyncAt}
          lastDeviceCount={model.lastDeviceCount}
          lastSyncError={model.lastSyncError}
          draft={model.draft}
          isLoadingDraft={model.settingsQuery.isLoading}
          onUpdateDraft={model.updateDraft}
          onSetError={model.setError}
          onRefresh={model.refresh}
          onSave={() => void model.save()}
          onReset={model.reset}
          onRunSync={() => void model.runSync()}
        />
      </div>
    </SettingsTabShell>
  )
}

export default SettingsZigbee2mqttTab

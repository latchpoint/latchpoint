import { SettingsTabShell } from '@/features/settings/components/SettingsTabShell'
import { MqttSettingsCard } from '@/features/mqtt/components/MqttSettingsCard'
import { useMqttSettingsModel } from '@/features/mqtt/hooks/useMqttSettingsModel'

export function SettingsMqttTab() {
  const model = useMqttSettingsModel()

  return (
    <SettingsTabShell isAdmin={model.isAdmin} error={model.error} notice={model.notice}>
      <MqttSettingsCard
        isAdmin={model.isAdmin}
        isBusy={model.isBusy}
        draft={model.draft}
        settings={model.settingsQuery.data}
        isLoading={model.settingsQuery.isLoading}
        connected={model.statusQuery.data?.connected}
        enabled={model.statusQuery.data?.enabled}
        lastError={model.statusQuery.data?.lastError ?? undefined}
        zigbee2mqttEnabled={Boolean(model.zigbee2mqttSettingsQuery.data?.enabled)}
        frigateEnabled={Boolean(model.frigateSettingsQuery.data?.enabled)}
        onRefresh={model.refresh}
        onReset={model.reset}
        onSave={() => void model.save()}
        onTest={() => void model.test()}
        onClearPassword={() => void model.clearPassword()}
        onSetDraft={model.setDraft}
        hasInitialDraft={Boolean(model.initialDraft)}
      />
    </SettingsTabShell>
  )
}

export default SettingsMqttTab

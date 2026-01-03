import { ConnectionPill } from '@/features/integrations/components/ConnectionStatus'
import { BooleanStatusPill } from '@/features/integrations/components/BooleanStatusPill'
import { Pill } from '@/components/ui/pill'

type Props = {
  mqttConnected: boolean
  z2mEnabled: boolean
  z2mConnected: boolean
  lastSyncAt: string | null
  lastDeviceCount: number | null
  lastSyncError: string | null
}

export function Zigbee2mqttStatusPills({ mqttConnected, z2mEnabled, z2mConnected, lastSyncAt, lastDeviceCount, lastSyncError }: Props) {
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:items-center sm:gap-2">
      {/* Primary status group: connection states */}
      <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
        <ConnectionPill connected={mqttConnected} enabled labels={{ connected: 'MQTT connected', disconnected: 'MQTT disconnected' }} />
        <ConnectionPill
          connected={z2mConnected}
          enabled={z2mEnabled}
          labels={{ connected: 'Zigbee2MQTT alive', disconnected: 'Zigbee2MQTT disconnected' }}
        />
        <BooleanStatusPill
          value={z2mEnabled}
          trueLabel="Enabled"
          falseLabel="Disabled"
          trueVariant="default"
          falseVariant="default"
          trueClassName="text-success"
          falseClassName="text-muted-foreground"
        />
      </div>
      {/* Secondary status group: sync info */}
      {(lastSyncAt || typeof lastDeviceCount === 'number' || lastSyncError) ? (
        <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
          {lastSyncAt ? <Pill className="text-muted-foreground">{`Last sync: ${new Date(lastSyncAt).toLocaleString()}`}</Pill> : null}
          {typeof lastDeviceCount === 'number' ? <Pill className="text-muted-foreground">{`Devices: ${lastDeviceCount}`}</Pill> : null}
          {lastSyncError ? <Pill className="text-destructive">{`Sync error: ${lastSyncError}`}</Pill> : null}
        </div>
      ) : null}
    </div>
  )
}

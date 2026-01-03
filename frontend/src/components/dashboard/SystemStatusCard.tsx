import { useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Wifi, WifiOff, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { queryKeys } from '@/types'
import { useWebSocketStatus } from '@/hooks/useWebSocketStatus'
import { useAlarmStateQuery, useSensorsQuery, useRecentEventsQuery } from '@/hooks/useAlarmQueries'
import { useHomeAssistantStatus } from '@/hooks/useHomeAssistant'
import { useFrigateStatusQuery } from '@/hooks/useFrigate'
import { useMqttStatusQuery } from '@/hooks/useMqtt'
import { useZigbee2mqttStatusQuery } from '@/hooks/useZigbee2mqtt'
import { useZwavejsStatusQuery } from '@/hooks/useZwavejs'

function formatTimestamp(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

export function SystemStatusCard() {
  const queryClient = useQueryClient()
  const wsStatus = useWebSocketStatus().data

  const alarmStateQuery = useAlarmStateQuery()
  const sensorsQuery = useSensorsQuery()
  const recentEventsQuery = useRecentEventsQuery()

  const alarmState = alarmStateQuery.data ?? null
  const isLoading = alarmStateQuery.isFetching || sensorsQuery.isFetching || recentEventsQuery.isFetching

  const haQuery = useHomeAssistantStatus()
  const mqttQuery = useMqttStatusQuery()
  const zwavejsQuery = useZwavejsStatusQuery()
  const zigbee2mqttQuery = useZigbee2mqttStatusQuery()
  const frigateQuery = useFrigateStatusQuery()

  const ha =
    haQuery.data ??
    (haQuery.isError ? { configured: true, reachable: false, error: 'Failed to check status' } : null)

  const mqtt =
    mqttQuery.data ??
    (mqttQuery.isError
      ? { configured: true, enabled: true, connected: false, lastError: 'Failed to check status' }
      : null)

  const zwavejs =
    zwavejsQuery.data ??
    (zwavejsQuery.isError
      ? { configured: true, enabled: true, connected: false, lastError: 'Failed to check status' }
      : null)

  const zigbee2mqtt =
    zigbee2mqttQuery.data ??
    (zigbee2mqttQuery.isError
      ? {
          enabled: true,
          baseTopic: '',
          mqtt: { configured: true, enabled: true, connected: false, lastError: 'Failed to check status' },
          sync: { lastSyncAt: null, lastDeviceCount: null, lastError: 'Failed to check status' },
        }
      : null)

  const frigate =
    frigateQuery.data ??
    (frigateQuery.isError
      ? {
          enabled: true,
          eventsTopic: '',
          retentionSeconds: 0,
          available: false,
          mqtt: { configured: true, enabled: true, connected: false, lastError: 'Failed to check status' },
          ingest: { lastIngestAt: null, lastError: 'Failed to check status' },
        }
      : null)

  const statusLabel = useMemo(() => {
    switch (wsStatus) {
      case 'connected':
        return 'Connected'
      case 'connecting':
        return 'Connecting…'
      case 'error':
        return 'Error'
      case 'disconnected':
      default:
        return 'Offline'
    }
  }, [wsStatus])

  const StatusIcon = wsStatus === 'connected' ? Wifi : WifiOff

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">System Status</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <StatusIcon
              className={cn(
                'h-4 w-4',
                wsStatus === 'connected' ? 'text-success' : 'text-muted-foreground'
              )}
            />
            <span className="text-sm">{statusLabel}</span>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={isLoading}
            onClick={() => {
              void queryClient.invalidateQueries({ queryKey: queryKeys.alarm.state })
              void queryClient.invalidateQueries({ queryKey: queryKeys.sensors.all })
              void queryClient.invalidateQueries({ queryKey: queryKeys.events.recent })
              void queryClient.invalidateQueries({ queryKey: queryKeys.homeAssistant.status })
              void queryClient.invalidateQueries({ queryKey: queryKeys.mqtt.status })
              void queryClient.invalidateQueries({ queryKey: queryKeys.zwavejs.status })
              void queryClient.invalidateQueries({ queryKey: queryKeys.zigbee2mqtt.status })
              void queryClient.invalidateQueries({ queryKey: queryKeys.frigate.status })
            }}
          >
            <RefreshCw />
            Refresh
          </Button>
        </div>

        {ha?.configured && (
          <div className="rounded-md border p-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">Home Assistant</span>
              <span className={cn('text-xs', ha.reachable ? 'text-success' : 'text-muted-foreground')}>
                {ha.reachable ? 'Connected' : 'Offline'}
              </span>
            </div>
            {ha.configured && !ha.reachable && ha.error && (
              <div className="mt-1 text-xs text-muted-foreground">{ha.error}</div>
            )}
          </div>
        )}

        {mqtt?.enabled && (
          <div className="rounded-md border p-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">MQTT</span>
              <span className={cn('text-xs', mqtt.connected ? 'text-success' : 'text-muted-foreground')}>
                {!mqtt.configured ? 'Not configured' : mqtt.connected ? 'Connected' : 'Offline'}
              </span>
            </div>
            {mqtt.enabled && !mqtt.connected && mqtt.lastError && (
              <div className="mt-1 text-xs text-muted-foreground">{mqtt.lastError}</div>
            )}
          </div>
        )}

        {zwavejs?.enabled && (
          <div className="rounded-md border p-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">Z-Wave JS</span>
              <span className={cn('text-xs', zwavejs.connected ? 'text-success' : 'text-muted-foreground')}>
                {!zwavejs.configured ? 'Not configured' : zwavejs.connected ? 'Connected' : 'Offline'}
              </span>
            </div>
            {zwavejs.enabled && !zwavejs.connected && zwavejs.lastError && (
              <div className="mt-1 text-xs text-muted-foreground">{zwavejs.lastError}</div>
            )}
          </div>
        )}

        {zigbee2mqtt?.enabled && (
          <div className="rounded-md border p-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">Zigbee2MQTT</span>
              <span
                className={cn(
                  'text-xs',
                  zigbee2mqtt.mqtt.connected ? 'text-success' : 'text-muted-foreground'
                )}
              >
                {!zigbee2mqtt.mqtt.configured ? 'Not configured' : zigbee2mqtt.mqtt.connected ? 'Connected' : 'Offline'}
              </span>
            </div>
            {zigbee2mqtt.enabled && (zigbee2mqtt.sync.lastError || zigbee2mqtt.mqtt.lastError) && (
              <div className="mt-1 text-xs text-muted-foreground">
                {zigbee2mqtt.sync.lastError ?? zigbee2mqtt.mqtt.lastError}
              </div>
            )}
          </div>
        )}

        {frigate?.enabled && (
          <div className="rounded-md border p-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">Frigate</span>
              <span
                className={cn('text-xs', frigate.available ? 'text-success' : 'text-muted-foreground')}
              >
                {!frigate.mqtt.configured ? 'Not configured' : frigate.available ? 'Available' : 'Offline'}
              </span>
            </div>
            {frigate.enabled && (frigate.ingest.lastError || frigate.mqtt.lastError) && (
              <div className="mt-1 text-xs text-muted-foreground">{frigate.ingest.lastError ?? frigate.mqtt.lastError}</div>
            )}
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
          <div className="rounded-md border p-2">
            <div className="font-medium text-foreground">State Since</div>
            <div>{formatTimestamp(alarmState?.enteredAt)}</div>
          </div>
          <div className="rounded-md border p-2">
            <div className="font-medium text-foreground">Next Transition</div>
            <div>{formatTimestamp(alarmState?.exitAt)}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default SystemStatusCard

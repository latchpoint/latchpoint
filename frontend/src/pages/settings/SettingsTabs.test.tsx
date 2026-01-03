import React from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { SettingsAlarmTab } from '@/pages/settings/SettingsAlarmTab'
import { SettingsMqttTab } from '@/pages/settings/SettingsMqttTab'
import { SettingsHomeAssistantTab } from '@/pages/settings/SettingsHomeAssistantTab'
import { SettingsZwavejsTab } from '@/pages/settings/SettingsZwavejsTab'
import { SettingsZigbee2mqttTab } from '@/pages/settings/SettingsZigbee2mqttTab'
import { SettingsFrigateTab } from '@/pages/settings/SettingsFrigateTab'
import { SettingsNotificationsTab } from '@/pages/settings/SettingsNotificationsTab'
import { UserRole } from '@/lib/constants'

let isAdmin = true

vi.mock('@/features/settings/components/SettingsTabShell', () => {
  return {
    SettingsTabShell: (props: any) => (
      <div data-testid="SettingsTabShell" data-admin={props.isAdmin ? '1' : '0'}>
        {props.children}
      </div>
    ),
  }
})

vi.mock('@/components/ui/loading-inline', () => {
  return { LoadingInline: () => <div>LoadingInline</div> }
})

vi.mock('@/features/alarmSettings/hooks/useAlarmSettingsTabModel', () => {
  return {
    useAlarmSettingsTabModel: () => ({
      isAdmin,
      loadError: null,
      error: null,
      notice: null,
      isLoading: false,
      initialDraft: {},
      draft: { code_arm_required: false },
      setDraft: vi.fn(),
      reset: vi.fn(),
      save: vi.fn(),
      settingsQuery: { isLoading: false, refetch: vi.fn() },
    }),
  }
})

vi.mock('@/features/alarmSettings/components/AlarmBehaviorCard', () => {
  return { AlarmBehaviorCard: () => <div>AlarmBehaviorCard</div> }
})
vi.mock('@/features/alarmSettings/components/AlarmArmModesCard', () => {
  return { AlarmArmModesCard: () => <div>AlarmArmModesCard</div> }
})
vi.mock('@/features/alarmSettings/components/AlarmTimingCard', () => {
  return { AlarmTimingCard: () => <div>AlarmTimingCard</div> }
})
vi.mock('@/features/alarmSettings/components/SystemSettingsCard', () => {
  return { SystemSettingsCard: () => <div>SystemSettingsCard</div> }
})

vi.mock('@/features/mqtt/hooks/useMqttSettingsModel', () => {
  return {
    useMqttSettingsModel: () => ({
      isAdmin,
      isBusy: false,
      error: null,
      notice: null,
      draft: { enabled: false },
      initialDraft: {},
      settingsQuery: { data: null, isLoading: false },
      statusQuery: { data: { connected: true, enabled: true, lastError: null } },
      zigbee2mqttSettingsQuery: { data: { enabled: false } },
      frigateSettingsQuery: { data: { enabled: false } },
      refresh: vi.fn(),
      reset: vi.fn(),
      save: vi.fn(),
      test: vi.fn(),
      clearPassword: vi.fn(),
      setDraft: vi.fn(),
    }),
  }
})
vi.mock('@/features/mqtt/components/MqttSettingsCard', () => {
  return { MqttSettingsCard: () => <div>MqttSettingsCard</div> }
})

vi.mock('@/features/homeAssistant/hooks/useHomeAssistantSettingsModel', () => {
  return {
    useHomeAssistantSettingsModel: () => ({
      isAdmin,
      error: null,
      notice: null,
      mqttReady: true,
      haConnectionDraft: { baseUrl: '', token: '' },
      setHaConnectionDraft: vi.fn(),
      haStatusQuery: { data: { reachable: true, configured: true, error: null } },
      haSettingsQuery: { isLoading: false, isError: false, error: null },
      updateHaSettingsMutation: { isPending: false },
      clearToken: vi.fn(),
      refreshConnection: vi.fn(),
      resetConnection: vi.fn(),
      saveConnection: vi.fn(),
      haMqttEntityDraft: {},
      setHaMqttEntityDraft: vi.fn(),
      haMqttEntityStatus: null,
      updateHaMqttAlarmEntityMutation: { isPending: false },
      publishHaMqttDiscoveryMutation: { isPending: false },
      saveMqttEntity: vi.fn(),
      publishDiscovery: vi.fn(),
      refreshMqttEntity: vi.fn(),
    }),
  }
})
vi.mock('@/features/homeAssistant/components/HomeAssistantOverviewCard', () => {
  return { HomeAssistantOverviewCard: () => <div>HomeAssistantOverviewCard</div> }
})
vi.mock('@/features/homeAssistant/components/HomeAssistantConnectionCard', () => {
  return { HomeAssistantConnectionCard: () => <div>HomeAssistantConnectionCard</div> }
})
vi.mock('@/features/homeAssistant/components/HomeAssistantMqttAlarmEntityCard', () => {
  return { HomeAssistantMqttAlarmEntityCard: () => <div>HomeAssistantMqttAlarmEntityCard</div> }
})

vi.mock('@/features/zwavejs/hooks/useZwavejsSettingsModel', () => {
  return {
    useZwavejsSettingsModel: () => ({
      isAdmin,
      error: null,
      notice: null,
      isBusy: false,
      draft: { enabled: false },
      initialDraft: {},
      setDraft: vi.fn(),
      settingsQuery: { isLoading: false },
      statusQuery: { data: { connected: true, enabled: true, lastError: null } },
      refresh: vi.fn(),
      reset: vi.fn(),
      save: vi.fn(),
      test: vi.fn(),
      sync: vi.fn(),
    }),
  }
})
vi.mock('@/features/zwavejs/components/ZwavejsSettingsCard', () => {
  return { ZwavejsSettingsCard: () => <div>ZwavejsSettingsCard</div> }
})

vi.mock('@/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel', () => {
  return {
    useZigbee2mqttSettingsModel: () => ({
      isAdmin,
      error: null,
      notice: null,
      isBusy: false,
      mqttReady: true,
      mqttConnected: true,
      z2mEnabled: true,
      z2mConnected: true,
      lastSyncAt: null,
      lastDeviceCount: 0,
      lastSyncError: null,
      draft: { enabled: true },
      settingsQuery: { isLoading: false },
      updateDraft: vi.fn(),
      setError: vi.fn(),
      refresh: vi.fn(),
      save: vi.fn(),
      reset: vi.fn(),
      runSync: vi.fn(),
    }),
  }
})
vi.mock('@/features/zigbee2mqtt/components/Zigbee2mqttSettingsCard', () => {
  return { Zigbee2mqttSettingsCard: () => <div>Zigbee2mqttSettingsCard</div> }
})

vi.mock('@/features/frigate/hooks/useFrigateSettingsModel', () => {
  return {
    useFrigateSettingsModel: () => ({
      isAdmin,
      error: null,
      notice: null,
      isBusy: false,
      mqttReady: true,
      mqttConnected: true,
      draft: { enabled: false },
      setDraft: vi.fn(),
      setError: vi.fn(),
      refresh: vi.fn(),
      reset: vi.fn(),
      save: vi.fn(),
      statusQuery: { isLoading: false, data: { available: true }, error: null },
      settingsQuery: { isLoading: false },
      detectionsQuery: { isLoading: false, isFetching: false, data: [], error: null, refetch: vi.fn() },
    }),
  }
})
vi.mock('@/features/frigate/components/FrigateOverviewCard', () => {
  return { FrigateOverviewCard: () => <div>FrigateOverviewCard</div> }
})
vi.mock('@/features/frigate/components/FrigateSettingsCard', () => {
  return { FrigateSettingsCard: () => <div>FrigateSettingsCard</div> }
})
vi.mock('@/features/frigate/components/FrigateRecentDetectionsCard', () => {
  return { FrigateRecentDetectionsCard: () => <div>FrigateRecentDetectionsCard</div> }
})

vi.mock('@/hooks/useAuthQueries', () => {
  return {
    useCurrentUserQuery: () => ({ data: { id: 'a1', role: isAdmin ? UserRole.ADMIN : UserRole.USER } }),
  }
})

vi.mock('@/features/notifications/components/NotificationProvidersCard', () => {
  return { NotificationProvidersCard: (props: any) => <div>NotificationProvidersCard {String(props.isAdmin)}</div> }
})

describe('Settings tabs', () => {
  beforeEach(() => {
    isAdmin = true
  })

  it('renders alarm settings tab', () => {
    render(<SettingsAlarmTab />)
    expect(document.querySelector('[data-testid="SettingsTabShell"]')).toBeTruthy()
    expect(document.body.textContent).toContain('AlarmTimingCard')
    expect(document.body.textContent).toContain('AlarmBehaviorCard')
    expect(document.body.textContent).toContain('AlarmArmModesCard')
    expect(document.body.textContent).toContain('SystemSettingsCard')
  })

  it('renders integration settings tabs', () => {
    render(<SettingsMqttTab />)
    expect(document.body.textContent).toContain('MqttSettingsCard')

    render(<SettingsHomeAssistantTab />)
    expect(document.body.textContent).toContain('HomeAssistantOverviewCard')
    expect(document.body.textContent).toContain('HomeAssistantConnectionCard')
    expect(document.body.textContent).toContain('HomeAssistantMqttAlarmEntityCard')

    render(<SettingsZwavejsTab />)
    expect(document.body.textContent).toContain('ZwavejsSettingsCard')

    render(<SettingsZigbee2mqttTab />)
    expect(document.body.textContent).toContain('Zigbee2mqttSettingsCard')

    render(<SettingsFrigateTab />)
    expect(document.body.textContent).toContain('FrigateOverviewCard')
    expect(document.body.textContent).toContain('FrigateSettingsCard')
    expect(document.body.textContent).toContain('FrigateRecentDetectionsCard')
  })

  it('renders notifications settings tab and passes admin flag', () => {
    isAdmin = false
    render(<SettingsNotificationsTab />)
    expect(document.body.textContent).toContain('NotificationProvidersCard false')
  })
})


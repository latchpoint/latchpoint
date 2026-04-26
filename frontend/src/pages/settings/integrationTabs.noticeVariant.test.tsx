import { describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'

const tabShellSpy = vi.fn(({ children }: { children: React.ReactNode }) => <>{children}</>)

vi.mock('@/features/settings/components/SettingsTabShell', () => ({
  SettingsTabShell: (props: Record<string, unknown>) => {
    tabShellSpy(props)
    return <>{(props as { children?: React.ReactNode }).children ?? null}</>
  },
}))

// Keep the card renders as lightweight placeholders to avoid pulling in every
// deep child. Only the tab page's prop wiring is under test here.
vi.mock('@/features/mqtt/components/MqttSettingsCard', () => ({
  MqttSettingsCard: () => <div data-testid="mqtt-card" />,
}))
vi.mock('@/features/zwavejs/components/ZwavejsSettingsCard', () => ({
  ZwavejsSettingsCard: () => <div data-testid="zwavejs-card" />,
}))
vi.mock('@/features/zigbee2mqtt/components/Zigbee2mqttSettingsCard', () => ({
  Zigbee2mqttSettingsCard: () => <div data-testid="z2m-card" />,
}))
vi.mock('@/features/frigate/components/FrigateSettingsCard', () => ({
  FrigateSettingsCard: () => <div data-testid="frigate-card" />,
}))
vi.mock('@/features/homeAssistant/components/HomeAssistantConnectionCard', () => ({
  HomeAssistantConnectionCard: () => <div data-testid="ha-conn-card" />,
}))
vi.mock('@/features/homeAssistant/components/HomeAssistantMqttAlarmEntityCard', () => ({
  HomeAssistantMqttAlarmEntityCard: () => <div data-testid="ha-mqtt-card" />,
}))
vi.mock('@/features/homeAssistant/components/HomeAssistantOverviewCard', () => ({
  HomeAssistantOverviewCard: () => <div data-testid="ha-overview-card" />,
}))
vi.mock('@/features/frigate/components/FrigateOverviewCard', () => ({
  FrigateOverviewCard: () => <div data-testid="frigate-overview-card" />,
}))
vi.mock('@/features/frigate/components/FrigateRecentDetectionsCard', () => ({
  FrigateRecentDetectionsCard: () => <div data-testid="frigate-recent-card" />,
}))

const makeModelStub = (noticeVariant: 'info' | 'success' = 'success') => ({
  isAdmin: true,
  isBusy: false,
  draft: {},
  maskedFlags: {},
  error: null,
  notice: 'All good',
  noticeVariant,
  saveDisabled: false,
  handleFieldChange: vi.fn(),
  save: vi.fn(),
  refresh: vi.fn(),
  settingsQuery: { isLoading: false, data: {} },
  statusQuery: { data: { connected: true, enabled: true } },
  zigbee2mqttSettingsQuery: { data: null },
  frigateSettingsQuery: { data: null },
  // zwavejs
  syncDisabled: false,
  sync: vi.fn(),
  // zigbee2mqtt
  mqttConnected: true,
  mqttReady: true,
  z2mEnabled: false,
  z2mConnected: false,
  lastSyncAt: null,
  lastDeviceCount: null,
  lastSyncError: null,
  setError: vi.fn(),
  setNotice: vi.fn(),
  updateDraft: vi.fn(),
  reset: vi.fn(),
  runSync: vi.fn(),
  devicesQuery: { data: [] },
  // frigate
  setDraft: vi.fn(),
  detectionsQuery: { data: [] },
  // HA
  connectionDraft: {},
  haMqttEntityDraft: {},
  haMqttEntityStatus: 'ok',
  haStatusQuery: { data: {} },
  haSettingsQuery: { data: {} },
  setHaMqttEntityDraft: vi.fn(),
  updateHaMqttAlarmEntityMutation: { isPending: false },
  publishHaMqttDiscoveryMutation: { isPending: false },
  saveConnection: vi.fn(),
  connectionSaveDisabled: false,
  isConnectionSaving: false,
  refreshConnection: vi.fn(),
  refreshMqttEntity: vi.fn(),
  saveMqttEntity: vi.fn(),
  publishDiscovery: vi.fn(),
})

vi.mock('@/features/mqtt/hooks/useMqttSettingsModel', () => ({
  useMqttSettingsModel: () => makeModelStub('success'),
}))
vi.mock('@/features/zwavejs/hooks/useZwavejsSettingsModel', () => ({
  useZwavejsSettingsModel: () => makeModelStub('success'),
}))
vi.mock('@/features/zigbee2mqtt/hooks/useZigbee2mqttSettingsModel', () => ({
  useZigbee2mqttSettingsModel: () => makeModelStub('success'),
}))
vi.mock('@/features/frigate/hooks/useFrigateSettingsModel', () => ({
  useFrigateSettingsModel: () => makeModelStub('success'),
}))
vi.mock('@/features/homeAssistant/hooks/useHomeAssistantSettingsModel', () => ({
  useHomeAssistantSettingsModel: () => makeModelStub('success'),
}))

describe('AC-18: integration tab pages forward noticeVariant to SettingsTabShell', () => {
  it('SettingsMqttTab forwards noticeVariant', async () => {
    tabShellSpy.mockClear()
    const { SettingsMqttTab } = await import('@/pages/settings/SettingsMqttTab')
    render(<SettingsMqttTab />)
    expect(tabShellSpy).toHaveBeenCalled()
    expect(tabShellSpy.mock.calls[0][0]).toMatchObject({ noticeVariant: 'success', notice: 'All good' })
  })

  it('SettingsZwavejsTab forwards noticeVariant', async () => {
    tabShellSpy.mockClear()
    const { SettingsZwavejsTab } = await import('@/pages/settings/SettingsZwavejsTab')
    render(<SettingsZwavejsTab />)
    expect(tabShellSpy).toHaveBeenCalled()
    expect(tabShellSpy.mock.calls[0][0]).toMatchObject({ noticeVariant: 'success' })
  })

  it('SettingsZigbee2mqttTab forwards noticeVariant', async () => {
    tabShellSpy.mockClear()
    const { SettingsZigbee2mqttTab } = await import('@/pages/settings/SettingsZigbee2mqttTab')
    render(<SettingsZigbee2mqttTab />)
    expect(tabShellSpy).toHaveBeenCalled()
    expect(tabShellSpy.mock.calls[0][0]).toMatchObject({ noticeVariant: 'success' })
  })

  it('SettingsFrigateTab forwards noticeVariant', async () => {
    tabShellSpy.mockClear()
    const { SettingsFrigateTab } = await import('@/pages/settings/SettingsFrigateTab')
    render(<SettingsFrigateTab />)
    expect(tabShellSpy).toHaveBeenCalled()
    expect(tabShellSpy.mock.calls[0][0]).toMatchObject({ noticeVariant: 'success' })
  })

  it('SettingsHomeAssistantTab forwards noticeVariant', async () => {
    tabShellSpy.mockClear()
    const { SettingsHomeAssistantTab } = await import('@/pages/settings/SettingsHomeAssistantTab')
    render(<SettingsHomeAssistantTab />)
    expect(tabShellSpy).toHaveBeenCalled()
    expect(tabShellSpy.mock.calls[0][0]).toMatchObject({ noticeVariant: 'success' })
  })
})

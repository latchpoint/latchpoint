export type ControlPanelIntegrationType = 'zwavejs' | 'home_assistant'
export type ControlPanelKind = 'ring_keypad_v2'

export type ControlPanelAction = 'disarm' | 'arm_home' | 'arm_away' | 'cancel'

export interface ControlPanelDevice {
  id: number
  name: string
  integrationType: ControlPanelIntegrationType
  kind: ControlPanelKind
  enabled: boolean
  externalKey: string
  externalId: Record<string, unknown>
  beepVolume: number
  actionMap: Record<string, unknown>
  lastSeenAt: string | null
  lastError: string
  createdAt: string
  updatedAt: string
}

export interface ControlPanelDeviceCreate {
  name: string
  integrationType: ControlPanelIntegrationType
  kind: ControlPanelKind
  enabled?: boolean
  externalId: Record<string, unknown>
  externalKey?: string
  actionMap?: Record<string, unknown>
}

export interface ControlPanelDeviceUpdate {
  name?: string
  enabled?: boolean
  externalId?: Record<string, unknown>
  externalKey?: string
  beepVolume?: number
  actionMap?: Record<string, unknown>
  lastError?: string
}

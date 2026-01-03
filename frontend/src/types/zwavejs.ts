export interface ZwavejsStatus {
  configured: boolean
  enabled: boolean
  connected: boolean
  homeId: number | null
  lastConnectAt: string | null
  lastDisconnectAt: string | null
  lastError: string | null
}

export interface ZwavejsSettings {
  enabled: boolean
  wsUrl: string
  connectTimeoutSeconds: number
  reconnectMinSeconds: number
  reconnectMaxSeconds: number
  hasApiToken?: boolean
}

export interface ZwavejsSettingsUpdate {
  enabled?: boolean
  wsUrl?: string
  apiToken?: string | null
  connectTimeoutSeconds?: number
  reconnectMinSeconds?: number
  reconnectMaxSeconds?: number
}

export interface ZwavejsTestConnectionRequest {
  wsUrl: string
  connectTimeoutSeconds?: number
}

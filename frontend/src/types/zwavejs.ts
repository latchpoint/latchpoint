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

export interface MqttStatus {
  configured: boolean
  enabled: boolean
  connected: boolean
  lastConnectAt: string | null
  lastDisconnectAt: string | null
  lastError: string | null
}

export interface MqttSettings {
  enabled: boolean
  host: string
  port: number
  username: string
  useTls: boolean
  tlsInsecure: boolean
  clientId: string
  keepaliveSeconds: number
  connectTimeoutSeconds: number
  hasPassword: boolean
}

export interface MqttSettingsUpdate {
  enabled?: boolean
  host?: string
  port?: number
  username?: string
  password?: string
  useTls?: boolean
  tlsInsecure?: boolean
  clientId?: string
  keepaliveSeconds?: number
  connectTimeoutSeconds?: number
}

export interface MqttTestConnectionRequest {
  host: string
  port: number
  username?: string
  password?: string
  useTls?: boolean
  tlsInsecure?: boolean
  clientId?: string
  keepaliveSeconds?: number
  connectTimeoutSeconds?: number
}

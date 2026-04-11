/**
 * Notification provider types and interfaces.
 * Providers are DB-backed with full CRUD via the UI (ADR-0079).
 */

export type NotificationProviderType =
  | 'pushbullet'
  | 'discord'
  | 'email'
  | 'telegram'
  | 'slack'
  | 'webhook'
  | 'pushover'
  | 'ntfy'
  | 'home_assistant'

export interface NotificationProvider {
  id: string
  name: string
  providerType: NotificationProviderType
  config: Record<string, unknown>
  isEnabled: boolean
  createdAt: string
  updatedAt: string
}

export interface NotificationProviderTypeInfo {
  type: NotificationProviderType
  displayName: string
  configSchema: Record<string, unknown>
  encryptedFields: string[]
}

export interface NotificationTestResult {
  success: boolean
  message: string
  errorCode?: string
}

// Pushbullet-specific types
export type PushbulletTargetType = 'all' | 'device' | 'email' | 'channel'

export interface PushbulletConfig {
  accessToken: string
  targetType?: PushbulletTargetType
  defaultDeviceIden?: string
  defaultEmail?: string
  defaultChannelTag?: string
}

export interface PushbulletDevice {
  iden: string
  nickname: string
  model?: string
  type?: string
  pushable: boolean
}

export interface PushbulletUserInfo {
  name: string
  email: string
  maxUploadSize?: number
}

export interface PushbulletTokenValidation {
  valid: boolean
  user?: PushbulletUserInfo
  error?: string
}

// Pushbullet notification data
export interface PushbulletNotificationData {
  url?: string
  imageUrl?: string
  targetOverride?: {
    type: PushbulletTargetType
    deviceIden?: string
    email?: string
    channelTag?: string
  }
}

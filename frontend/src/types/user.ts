import type { UserRoleType } from '@/lib/constants'

export interface User {
  id: string
  email: string
  displayName: string
  role: UserRoleType
  isActive: boolean
  has2FA: boolean
  createdAt: string
  lastLogin: string | null
}

export interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
}

export interface LoginCredentials {
  email: string
  password: string
  totpCode?: string
}

export interface LoginResponse {
  user: User
  accessToken: string
  refreshToken: string
  requires2FA: boolean
}

export interface TokenPair {
  accessToken: string
  refreshToken: string
}

export interface UserNotificationPreference {
  id: number
  userId: string
  eventType: string
  enabledChannels: string[]
  haNotifyServices: string[]
  priorityThreshold: 'info' | 'warning' | 'critical'
  quietHoursStart: string | null
  quietHoursEnd: string | null
  includeCameraSnapshot: boolean
  ttsEnabled: boolean
  ttsMessageTemplate: string | null
}

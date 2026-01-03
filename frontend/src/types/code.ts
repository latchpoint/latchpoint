import type { AlarmStateType } from '@/lib/constants'

export type CodeType = 'permanent' | 'temporary' | 'one_time' | 'service'

export interface AlarmCode {
  id: number
  userId: string
  userDisplayName: string
  label: string
  codeType: CodeType
  pinLength: number
  isActive: boolean
  maxUses: number | null
  usesCount: number
  startAt: string | null // ISO datetime
  endAt: string | null // ISO datetime
  daysOfWeek: number | null // bitmask
  windowStart: string | null // HH:MM
  windowEnd: string | null // HH:MM
  allowedStates: AlarmStateType[]
  lastUsedAt: string | null
  createdAt: string
  updatedAt: string
}

export interface CodeUsage {
  id: number
  codeId: number
  usedAt: string
  entryPointId: number | null
  entryPointName: string | null
  action: 'arm' | 'disarm' | 'unlock'
  success: boolean
  ipAddress: string | null
  userAgent: string | null
}

export interface CreateCodeRequest {
  userId: string
  label?: string
  code: string // Plain text, will be hashed on server
  codeType?: CodeType
  startAt?: string | null
  endAt?: string | null
  daysOfWeek?: number | null
  windowStart?: string | null
  windowEnd?: string | null
  allowedStates?: AlarmStateType[]
  reauthPassword: string
}

export interface UpdateCodeRequest {
  code?: string // Only if changing the code
  label?: string
  isActive?: boolean
  startAt?: string | null
  endAt?: string | null
  daysOfWeek?: number | null
  windowStart?: string | null
  windowEnd?: string | null
  allowedStates?: AlarmStateType[]
  reauthPassword: string
}

export interface ValidateCodeRequest {
  code: string
  action: 'arm' | 'disarm'
  targetState?: AlarmStateType
}

export interface ValidateCodeResponse {
  valid: boolean
  codeId: number | null
  userId: string | null
  reason?: string // e.g., "expired", "outside_time_window", "max_uses_exceeded"
}

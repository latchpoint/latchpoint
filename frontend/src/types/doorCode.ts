export type DoorCodeType = 'permanent' | 'temporary' | 'one_time' | 'service'
export type DoorCodeSource = 'manual' | 'synced'

export interface DoorCodeLockAssignment {
  id: number
  lockEntityId: string
}

export interface DoorCode {
  id: number
  userId: string
  userDisplayName: string
  source: DoorCodeSource
  label: string
  codeType: DoorCodeType
  pinLength: number | null
  isActive: boolean
  maxUses: number | null
  usesCount: number
  startAt: string | null
  endAt: string | null
  daysOfWeek: number | null
  windowStart: string | null
  windowEnd: string | null
  lastUsedAt: string | null
  lastUsedLock: string | null
  lockAssignments: DoorCodeLockAssignment[]
  lockEntityIds: string[]
  createdAt: string
  updatedAt: string
}

export interface CreateDoorCodeRequest {
  userId?: string
  label?: string
  code: string
  codeType?: DoorCodeType
  startAt?: string | null
  endAt?: string | null
  daysOfWeek?: number | null
  windowStart?: string | null
  windowEnd?: string | null
  maxUses?: number | null
  lockEntityIds?: string[]
  reauthPassword: string
}

export interface UpdateDoorCodeRequest {
  code?: string
  label?: string
  isActive?: boolean
  startAt?: string | null
  endAt?: string | null
  daysOfWeek?: number | null
  windowStart?: string | null
  windowEnd?: string | null
  maxUses?: number | null
  lockEntityIds?: string[]
  reauthPassword: string
}

export interface LockConfigSyncRequest {
  userId: string
  reauthPassword: string
}

export interface LockConfigSyncScheduleWindow {
  daysOfWeek: number
  windowStart: string
  windowEnd: string
}

export interface LockConfigSyncSlotResult {
  slotIndex: number
  action: string
  doorCodeId: number | null
  pinKnown: boolean | null
  isActive: boolean | null
  scheduleApplied: boolean
  scheduleUnsupported: boolean
  schedule: LockConfigSyncScheduleWindow | null
  warnings: string[]
  error: string | null
}

export interface LockConfigSyncResult {
  lockEntityId: string
  nodeId: number
  created: number
  updated: number
  unchanged: number
  skipped: number
  dismissed: number
  deactivated: number
  errors: number
  timestamp: string
  slots: LockConfigSyncSlotResult[]
}

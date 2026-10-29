export type DoorCodeType = 'permanent' | 'temporary' | 'one_time' | 'service'
export type DoorCodeSource = 'manual' | 'synced'
export type DoorCodePushState = 'pending' | 'pushed' | 'failed'
/**
 * Where the code is in its start_at/end_at (end_at itself counts as expired),
 * from the backend (#145). Scheduled codes go on their locks at start_at, and
 * expired ones are turned off and taken off. Nothing counts uses yet, so
 * exhausted doesn't come up until that lands.
 */
export type DoorCodeValidity = 'scheduled' | 'valid' | 'expired' | 'exhausted'

export interface DoorCodeLockAssignment {
  id: number
  lockEntityId: string
}

export interface DoorCodeLockSlotAssignment {
  lockEntityId: string
  slotIndex: number | null
  /** The lock is being dropped from the code but its slot clear hasn't worked yet. */
  pendingRemoval: boolean
}

/** A slot latchpoint still has to clear (or check and clear) for this code. */
export interface DoorCodePendingSlotClear {
  lockEntityId: string
  slotIndex: number
  /** Set when the lock is being dropped from the code. */
  removing: boolean
}

export interface DoorCode {
  id: number
  userId: string
  userDisplayName: string
  source: DoorCodeSource
  label: string
  codeType: DoorCodeType
  pin: string | null
  pinLength: number | null
  isActive: boolean
  maxUses: number | null
  usesCount: number
  startAt: string | null
  endAt: string | null
  daysOfWeek: number | null
  windowStart: string | null
  windowEnd: string | null
  validity: DoorCodeValidity
  lastUsedAt: string | null
  lastUsedLock: string | null
  lockAssignments: DoorCodeLockAssignment[]
  lockEntityIds: string[]
  lockSlotAssignments: DoorCodeLockSlotAssignment[]
  pendingSlotClears: DoorCodePendingSlotClear[]
  pushState: DoorCodePushState
  lastPushAttemptAt: string | null
  lastPushError: string
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
  deactivated: number
  errors: number
  timestamp: string
  slots: LockConfigSyncSlotResult[]
  dryRun?: boolean
}

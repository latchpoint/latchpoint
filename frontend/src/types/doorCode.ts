export type DoorCodeType = 'permanent' | 'temporary' | 'one_time' | 'service'

export interface DoorCodeLockAssignment {
  id: number
  lockEntityId: string
}

export interface DoorCode {
  id: number
  userId: string
  userDisplayName: string
  label: string
  codeType: DoorCodeType
  pinLength: number
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


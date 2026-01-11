export type SchedulerLeaderLockStatus = {
  enabled: boolean
  acquired: boolean
  error: string | null
}

export type SchedulerRuntimeTaskStatus = {
  threadAlive: boolean
  currentlyRunning: boolean
  status: Record<string, unknown>
}

export type SchedulerRuntimeStatus = {
  running: boolean
  leaderLock: SchedulerLeaderLockStatus
  tasks: Record<string, SchedulerRuntimeTaskStatus>
}

export type SchedulerTaskHealth = {
  taskName: string
  displayName: string
  description: string | null
  instanceId: string
  observed: boolean
  enabled: boolean
  enabledReason: string | null
  scheduleType: string
  schedulePayload: Record<string, unknown>
  maxRuntimeSeconds: number | null
  nextRunAt: string | null
  lastStartedAt: string | null
  lastFinishedAt: string | null
  lastDurationSeconds: number | null
  isRunning: boolean
  consecutiveFailures: number
  lastErrorMessage: string | null
  lastHeartbeatAt: string | null
  status: 'ok' | 'disabled' | 'running' | 'failing' | 'stuck' | 'never_ran' | 'orphaned'
  stuckForSeconds: number | null
}

export type SchedulerStatusResponse = {
  instanceId: string
  runtime: SchedulerRuntimeStatus
  tasks: SchedulerTaskHealth[]
}

export type SchedulerTaskRun = {
  id: number
  taskName: string
  instanceId: string
  startedAt: string
  finishedAt: string | null
  status: string
  durationSeconds: number | null
  errorMessage: string | null
  consecutiveFailuresAtStart: number
  threadName: string
  createdAt: string
}

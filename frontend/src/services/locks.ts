import api from './api'
import type { DismissedAssignment, LockConfigSyncRequest, LockConfigSyncResult } from '@/types'
import { apiEndpoints } from './endpoints'

export const locksService = {
  async syncConfig(lockEntityId: string, req: LockConfigSyncRequest, options?: { dryRun?: boolean }): Promise<LockConfigSyncResult> {
    const url = options?.dryRun
      ? `${apiEndpoints.locks.syncConfig(lockEntityId)}?dry_run=true`
      : apiEndpoints.locks.syncConfig(lockEntityId)
    return api.post<LockConfigSyncResult>(url, req)
  },

  async getDismissedAssignments(lockEntityId: string): Promise<DismissedAssignment[]> {
    return api.get<DismissedAssignment[]>(apiEndpoints.locks.dismissedAssignments(lockEntityId))
  },

  async undismissAssignment(assignmentId: number, req: { reauthPassword: string }): Promise<DismissedAssignment> {
    return api.post<DismissedAssignment>(apiEndpoints.doorCodeAssignments.undismiss(assignmentId), req)
  },
}

export default locksService


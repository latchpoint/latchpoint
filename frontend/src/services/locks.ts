import api from './api'
import type { LockConfigSyncRequest, LockConfigSyncResult } from '@/types'
import { apiEndpoints } from './endpoints'

export const locksService = {
  async syncConfig(lockEntityId: string, req: LockConfigSyncRequest, options?: { dryRun?: boolean }): Promise<LockConfigSyncResult> {
    const url = options?.dryRun
      ? `${apiEndpoints.locks.syncConfig(lockEntityId)}?dry_run=true`
      : apiEndpoints.locks.syncConfig(lockEntityId)
    return api.post<LockConfigSyncResult>(url, req)
  },

}

export default locksService


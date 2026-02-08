import api from './api'
import type { LockConfigSyncRequest, LockConfigSyncResult } from '@/types'
import { apiEndpoints } from './endpoints'

export const locksService = {
  async syncConfig(lockEntityId: string, req: LockConfigSyncRequest): Promise<LockConfigSyncResult> {
    return api.post<LockConfigSyncResult>(apiEndpoints.locks.syncConfig(lockEntityId), req)
  },
}

export default locksService


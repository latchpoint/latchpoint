import api from './api'
import type { SystemConfigRow } from '@/types'
import { apiEndpoints } from './endpoints'

export const systemConfigService = {
  async list(): Promise<SystemConfigRow[]> {
    return api.get<SystemConfigRow[]>(apiEndpoints.systemConfig.all)
  },

  async update(key: string, changes: { value?: unknown; description?: string }): Promise<SystemConfigRow> {
    return api.patch<SystemConfigRow>(apiEndpoints.systemConfig.key(key), changes)
  },
}

export default systemConfigService

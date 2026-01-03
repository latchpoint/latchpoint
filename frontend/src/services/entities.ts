import api from './api'
import type { Entity } from '@/types'
import { apiEndpoints } from './endpoints'

export const entitiesService = {
  async list(): Promise<Entity[]> {
    return api.get<Entity[]>(apiEndpoints.entities.all)
  },

  async sync(): Promise<{ imported: number; updated: number; timestamp: string }> {
    return api.post<{ imported: number; updated: number; timestamp: string }>(apiEndpoints.entities.sync, {})
  },
}

export default entitiesService

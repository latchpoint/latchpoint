import api from './api'
import type { DoorCode, CreateDoorCodeRequest, UpdateDoorCodeRequest } from '@/types'
import { apiEndpoints } from './endpoints'

export const doorCodesService = {
  async getDoorCodes(params?: { userId?: string }): Promise<DoorCode[]> {
    return api.get<DoorCode[]>(apiEndpoints.doorCodes.all, params)
  },

  async getDoorCode(id: number): Promise<DoorCode> {
    return api.get<DoorCode>(apiEndpoints.doorCodes.detail(id))
  },

  async createDoorCode(req: CreateDoorCodeRequest): Promise<DoorCode> {
    return api.post<DoorCode>(apiEndpoints.doorCodes.all, req)
  },

  async updateDoorCode(id: number, req: UpdateDoorCodeRequest): Promise<DoorCode> {
    return api.patch<DoorCode>(apiEndpoints.doorCodes.detail(id), req)
  },

  async deleteDoorCode(id: number, req: { reauthPassword: string }): Promise<void> {
    return api.delete(apiEndpoints.doorCodes.detail(id), req)
  },
}

export default doorCodesService

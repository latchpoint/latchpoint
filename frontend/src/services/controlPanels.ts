import api from './api'
import type { ControlPanelDevice, ControlPanelDeviceCreate, ControlPanelDeviceUpdate } from '@/types'
import { apiEndpoints } from './endpoints'

export const controlPanelsService = {
  async list(): Promise<ControlPanelDevice[]> {
    return api.get<ControlPanelDevice[]>(apiEndpoints.controlPanels.all)
  },

  async create(payload: ControlPanelDeviceCreate): Promise<ControlPanelDevice> {
    return api.post<ControlPanelDevice>(apiEndpoints.controlPanels.all, payload)
  },

  async update(id: number, changes: ControlPanelDeviceUpdate): Promise<ControlPanelDevice> {
    return api.patch<ControlPanelDevice>(apiEndpoints.controlPanels.detail(id), changes)
  },

  async test(id: number): Promise<{ ok: boolean }> {
    return api.post<{ ok: boolean }>(apiEndpoints.controlPanels.test(id), {})
  },

  async delete(id: number): Promise<void> {
    return api.delete<void>(apiEndpoints.controlPanels.detail(id))
  },
}

export default controlPanelsService

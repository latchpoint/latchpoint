import api from './api'
import type { Sensor } from '@/types'
import { apiEndpoints } from './endpoints'

export const sensorsService = {
  async getSensors(): Promise<Sensor[]> {
    return api.get<Sensor[]>(apiEndpoints.sensors.all)
  },

  async getSensor(id: number): Promise<Sensor> {
    return api.get<Sensor>(apiEndpoints.sensors.detail(id))
  },

  async createSensor(sensor: {
    name: string
    entityId: string | null
    isActive: boolean
    isEntryPoint: boolean
  }): Promise<Sensor> {
    return api.post<Sensor>(apiEndpoints.sensors.all, sensor)
  },

  async updateSensor(id: number, sensor: Partial<Sensor>): Promise<Sensor> {
    return api.patch<Sensor>(apiEndpoints.sensors.detail(id), sensor)
  },

  async deleteSensor(id: number): Promise<void> {
    return api.delete(apiEndpoints.sensors.detail(id))
  },
}

export default sensorsService

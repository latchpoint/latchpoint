import api from './api'
import type {
  MqttSettings,
  MqttSettingsUpdate,
  MqttStatus,
  MqttTestConnectionRequest,
} from '@/types'
import { apiEndpoints } from './endpoints'

export const mqttService = {
  async getStatus(): Promise<MqttStatus> {
    return api.get<MqttStatus>(apiEndpoints.mqtt.status)
  },

  async getSettings(): Promise<MqttSettings> {
    return api.get<MqttSettings>(apiEndpoints.mqtt.settings)
  },

  async updateSettings(changes: MqttSettingsUpdate): Promise<MqttSettings> {
    return api.patch<MqttSettings>(apiEndpoints.mqtt.settings, changes)
  },

  async testConnection(payload: MqttTestConnectionRequest): Promise<{ ok: boolean }> {
    return api.post<{ ok: boolean }>(apiEndpoints.mqtt.test, payload)
  },
}

export default mqttService

import api from './api'
import type {
  MqttSettings,
  MqttStatus,
} from '@/types'
import { apiEndpoints } from './endpoints'

export const mqttService = {
  async getStatus(): Promise<MqttStatus> {
    return api.get<MqttStatus>(apiEndpoints.mqtt.status)
  },

  async getSettings(): Promise<MqttSettings> {
    return api.get<MqttSettings>(apiEndpoints.mqtt.settings)
  },
  async updateSettings(data: {
    keepaliveSeconds?: number
    connectTimeoutSeconds?: number
  }): Promise<MqttSettings> {
    return api.patch<MqttSettings>(apiEndpoints.mqtt.settings, data)
  },
}

export default mqttService

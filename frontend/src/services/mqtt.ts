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
}

export default mqttService

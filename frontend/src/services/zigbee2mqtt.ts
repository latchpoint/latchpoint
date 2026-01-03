import api from './api'
import type { Zigbee2mqttEntity, Zigbee2mqttSettings, Zigbee2mqttSettingsUpdate, Zigbee2mqttStatus, Zigbee2mqttSyncResult } from '@/types'
import { apiEndpoints } from './endpoints'

export const zigbee2mqttService = {
  async getStatus(): Promise<Zigbee2mqttStatus> {
    return api.get<Zigbee2mqttStatus>(apiEndpoints.integrations.zigbee2mqtt.status)
  },

  async getSettings(): Promise<Zigbee2mqttSettings> {
    return api.get<Zigbee2mqttSettings>(apiEndpoints.integrations.zigbee2mqtt.settings)
  },

  async updateSettings(changes: Zigbee2mqttSettingsUpdate): Promise<Zigbee2mqttSettings> {
    return api.patch<Zigbee2mqttSettings>(apiEndpoints.integrations.zigbee2mqtt.settings, changes)
  },

  async listDevices(): Promise<Zigbee2mqttEntity[]> {
    return api.get<Zigbee2mqttEntity[]>(apiEndpoints.integrations.zigbee2mqtt.devices)
  },

  async syncDevices(): Promise<Zigbee2mqttSyncResult> {
    return api.post<Zigbee2mqttSyncResult>(apiEndpoints.integrations.zigbee2mqtt.syncDevices, {})
  },
}

export default zigbee2mqttService

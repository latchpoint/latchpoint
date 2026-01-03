import api from './api'
import type {
  HomeAssistantMqttAlarmEntitySettings,
  HomeAssistantMqttAlarmEntitySettingsUpdate,
  HomeAssistantMqttAlarmEntityStatusResponse,
} from '@/types'
import { apiEndpoints } from './endpoints'

export const integrationsService = {
  homeAssistantMqttAlarmEntity: {
    async getSettings(): Promise<HomeAssistantMqttAlarmEntitySettings> {
      return api.get<HomeAssistantMqttAlarmEntitySettings>(apiEndpoints.integrations.homeAssistantMqttAlarmEntity.settings)
    },

    async updateSettings(
      changes: HomeAssistantMqttAlarmEntitySettingsUpdate
    ): Promise<HomeAssistantMqttAlarmEntitySettings> {
      return api.patch<HomeAssistantMqttAlarmEntitySettings>(
        apiEndpoints.integrations.homeAssistantMqttAlarmEntity.settings,
        changes
      )
    },

    async getStatus(): Promise<HomeAssistantMqttAlarmEntityStatusResponse> {
      return api.get<HomeAssistantMqttAlarmEntityStatusResponse>(apiEndpoints.integrations.homeAssistantMqttAlarmEntity.status)
    },

    async publishDiscovery(): Promise<{ ok: boolean }> {
      return api.post<{ ok: boolean }>(apiEndpoints.integrations.homeAssistantMqttAlarmEntity.publishDiscovery, {})
    },
  },
}

export default integrationsService

import api from './api'
import { apiEndpoints } from './endpoints'

export interface HomeAssistantStatus {
  configured: boolean
  reachable: boolean
  baseUrl?: string | null
  error?: string | null
}

export interface HomeAssistantConnectionSettings {
  enabled: boolean
  baseUrl: string
  connectTimeoutSeconds: number
  hasToken: boolean
}

export interface HomeAssistantEntity {
  entityId: string
  domain: string
  state: string
  name: string
  deviceClass?: string | null
  unitOfMeasurement?: string | null
  lastChanged?: string | null
}

export const homeAssistantService = {
  async getStatus(): Promise<HomeAssistantStatus> {
    return api.get<HomeAssistantStatus>(apiEndpoints.homeAssistant.status)
  },

  async getSettings(): Promise<HomeAssistantConnectionSettings> {
    return api.get<HomeAssistantConnectionSettings>(apiEndpoints.homeAssistant.settings)
  },

  async listEntities(): Promise<HomeAssistantEntity[]> {
    return api.getData<HomeAssistantEntity[]>(apiEndpoints.homeAssistant.entities)
  },

  async listNotifyServices(): Promise<string[]> {
    return api.getData<string[]>(apiEndpoints.homeAssistant.notifyServices)
  },
}

export default homeAssistantService

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
  [key: string]: unknown
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

/**
 * One field of a Home Assistant service, slimmed by the backend catalog
 * endpoint (ADR-0101). Keys arrive camelized by the API client, so a wire
 * field like `rgb_color` is exposed here as `rgbColor` — matching how rule
 * `data` keys appear in-app after the same transform.
 */
export interface HomeAssistantServiceField {
  name?: string
  description?: string
  required?: boolean
  example?: unknown
  default?: unknown
  selector?: Record<string, unknown> | null
}

export interface HomeAssistantServiceDefinition {
  domain: string
  service: string
  name: string
  description: string
  fields: Record<string, HomeAssistantServiceField>
  target?: Record<string, unknown>
}

export const homeAssistantService = {
  async getStatus(): Promise<HomeAssistantStatus> {
    return api.get<HomeAssistantStatus>(apiEndpoints.homeAssistant.status)
  },

  async getSettings(): Promise<HomeAssistantConnectionSettings> {
    return api.get<HomeAssistantConnectionSettings>(apiEndpoints.homeAssistant.settings)
  },

  async updateSettings(data: Record<string, unknown>): Promise<HomeAssistantConnectionSettings> {
    return api.patch<HomeAssistantConnectionSettings>(apiEndpoints.homeAssistant.settings, data)
  },

  async listEntities(): Promise<HomeAssistantEntity[]> {
    return api.getData<HomeAssistantEntity[]>(apiEndpoints.homeAssistant.entities)
  },

  async listServices(): Promise<HomeAssistantServiceDefinition[]> {
    return api.getData<HomeAssistantServiceDefinition[]>(apiEndpoints.homeAssistant.services)
  },

  async listNotifyServices(): Promise<string[]> {
    return api.getData<string[]>(apiEndpoints.homeAssistant.notifyServices)
  },
}

export default homeAssistantService

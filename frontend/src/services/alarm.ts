import api from './api'
import { apiEndpoints } from './endpoints'
import type {
  AlarmStateSnapshot,
  AlarmSettingsProfile,
  ArmRequest,
  DisarmRequest,
  AlarmEvent,
  AlarmSettingsProfileDetail,
  AlarmSettingsProfileMeta,
  PaginatedResponse,
  PaginationParams,
} from '@/types'

export const alarmService = {
  // State
  async getState(): Promise<AlarmStateSnapshot> {
    return api.get<AlarmStateSnapshot>(apiEndpoints.alarm.state)
  },

  async arm(request: ArmRequest): Promise<AlarmStateSnapshot> {
    return api.post<AlarmStateSnapshot>(apiEndpoints.alarm.arm, request)
  },

  async disarm(request: DisarmRequest): Promise<AlarmStateSnapshot> {
    return api.post<AlarmStateSnapshot>(apiEndpoints.alarm.disarm, request)
  },

  async cancelArming(code?: string): Promise<AlarmStateSnapshot> {
    return api.post<AlarmStateSnapshot>(apiEndpoints.alarm.cancelArming, { code })
  },

  async trigger(): Promise<AlarmStateSnapshot> {
    return api.post<AlarmStateSnapshot>(apiEndpoints.alarm.trigger)
  },

  // Settings
  async getSettings(): Promise<AlarmSettingsProfile> {
    return api.get<AlarmSettingsProfile>(apiEndpoints.alarm.settings)
  },

  async getSettingsProfiles(): Promise<AlarmSettingsProfileMeta[]> {
    return api.get<AlarmSettingsProfileMeta[]>(apiEndpoints.alarm.settingsProfiles)
  },

  async getSettingsProfile(id: number): Promise<AlarmSettingsProfileDetail> {
    return api.get<AlarmSettingsProfileDetail>(apiEndpoints.alarm.settingsProfile(id))
  },

  async createSettingsProfile(profile: { name: string }): Promise<AlarmSettingsProfileMeta> {
    return api.post<AlarmSettingsProfileMeta>(apiEndpoints.alarm.settingsProfiles, profile)
  },

  async updateSettingsProfile(
    id: number,
    changes: { name?: string; entries?: Array<{ key: string; value: unknown }> }
  ): Promise<AlarmSettingsProfileDetail> {
    return api.patch<AlarmSettingsProfileDetail>(apiEndpoints.alarm.settingsProfile(id), changes)
  },

  async deleteSettingsProfile(id: number): Promise<void> {
    return api.delete(apiEndpoints.alarm.settingsProfile(id))
  },

  async activateSettingsProfile(id: number): Promise<AlarmSettingsProfileMeta> {
    return api.post<AlarmSettingsProfileMeta>(apiEndpoints.alarm.activateSettingsProfile(id))
  },

  // Events
  async getEvents(params?: PaginationParams & {
    eventType?: string
    startDate?: string
    endDate?: string
    userId?: string
  }): Promise<PaginatedResponse<AlarmEvent>> {
    return api.getPaginated<AlarmEvent>(apiEndpoints.events.all, params ? { ...params } : undefined)
  },

  async getRecentEvents(limit: number = 10): Promise<AlarmEvent[]> {
    return api.getPaginatedItems<AlarmEvent>(apiEndpoints.events.all, {
      pageSize: limit,
      ordering: '-timestamp',
    })
  },

  async acknowledgeEvent(id: number): Promise<AlarmEvent> {
    return api.patch<AlarmEvent>(apiEndpoints.events.acknowledge(id), {})
  },
}

export default alarmService

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
    const raw = await api.get<AlarmSettingsProfileDetail | AlarmSettingsProfile>(apiEndpoints.alarm.settings)

    // The API may return either:
    //   (a) nested { profile, entries[] } — new format from AlarmSettingsProfileDetailSerializer
    //   (b) a flat object with settings inlined — envelope-unwrapped flat profile
    // Handle both gracefully.
    if ('entries' in raw && Array.isArray((raw as AlarmSettingsProfileDetail).entries)) {
      const { profile, entries } = raw as AlarmSettingsProfileDetail
      const entryMap = new Map(entries.map((e) => [e.key, e.value]))
      return {
        ...profile,
        delayTime: (entryMap.get('delay_time') as number) ?? 30,
        armingTime: (entryMap.get('arming_time') as number) ?? 10,
        triggerTime: (entryMap.get('trigger_time') as number) ?? 120,
        disarmAfterTrigger: (entryMap.get('disarm_after_trigger') as boolean) ?? false,
        codeArmRequired: (entryMap.get('code_arm_required') as boolean) ?? true,
        availableArmingStates: (entryMap.get('available_arming_states') as AlarmSettingsProfile['availableArmingStates']) ?? [],
        stateOverrides: (entryMap.get('state_overrides') as AlarmSettingsProfile['stateOverrides']) ?? {},
        audioVisualSettings: (entryMap.get('audio_visual_settings') as AlarmSettingsProfile['audioVisualSettings']) ?? { beepEnabled: true, countdownDisplayEnabled: true, colorCodingEnabled: true },
        sensorBehavior: (entryMap.get('sensor_behavior') as AlarmSettingsProfile['sensorBehavior']) ?? { warnOnOpenSensors: true, autoBypassEnabled: false, forceArmEnabled: true },
      }
    }

    // Flat format: already has all fields after camelCase transform by the API client.
    const flat = raw as AlarmSettingsProfile
    return {
      id: flat.id,
      name: flat.name,
      isActive: flat.isActive,
      createdAt: flat.createdAt,
      updatedAt: flat.updatedAt,
      delayTime: flat.delayTime ?? 30,
      armingTime: flat.armingTime ?? 10,
      triggerTime: flat.triggerTime ?? 120,
      disarmAfterTrigger: flat.disarmAfterTrigger ?? false,
      codeArmRequired: flat.codeArmRequired ?? true,
      availableArmingStates: flat.availableArmingStates ?? [],
      stateOverrides: flat.stateOverrides ?? {},
      audioVisualSettings: flat.audioVisualSettings ?? { beepEnabled: true, countdownDisplayEnabled: true, colorCodingEnabled: true },
      sensorBehavior: flat.sensorBehavior ?? { warnOnOpenSensors: true, autoBypassEnabled: false, forceArmEnabled: true },
    }
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

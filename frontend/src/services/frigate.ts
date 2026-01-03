import api from './api'
import type {
  FrigateDetection,
  FrigateDetectionDetail,
  FrigateOptions,
  FrigateSettings,
  FrigateSettingsUpdate,
  FrigateStatus,
} from '@/types'
import { apiEndpoints } from './endpoints'

export const frigateService = {
  async getStatus(): Promise<FrigateStatus> {
    return api.get<FrigateStatus>(apiEndpoints.integrations.frigate.status)
  },

  async getSettings(): Promise<FrigateSettings> {
    return api.get<FrigateSettings>(apiEndpoints.integrations.frigate.settings)
  },

  async updateSettings(changes: FrigateSettingsUpdate): Promise<FrigateSettings> {
    return api.patch<FrigateSettings>(apiEndpoints.integrations.frigate.settings, changes)
  },

  async getOptions(): Promise<FrigateOptions> {
    return api.get<FrigateOptions>(apiEndpoints.integrations.frigate.options)
  },

  async listDetections(params?: { limit?: number }): Promise<FrigateDetection[]> {
    return api.get<FrigateDetection[]>(apiEndpoints.integrations.frigate.detections, params)
  },

  async getDetection(id: number): Promise<FrigateDetectionDetail> {
    return api.get<FrigateDetectionDetail>(apiEndpoints.integrations.frigate.detection(id))
  },
}

export default frigateService

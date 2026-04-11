import api from './api'
import { apiEndpoints } from './endpoints'
import type {
  NotificationProvider,
  NotificationProviderTypeInfo,
  NotificationTestResult,
  PushbulletDevice,
} from '@/types/notifications'

export const notificationsService = {
  async listProviders(): Promise<NotificationProvider[]> {
    return api.get<NotificationProvider[]>(apiEndpoints.notifications.providers)
  },

  async getProvider(id: string): Promise<NotificationProvider> {
    return api.get<NotificationProvider>(apiEndpoints.notifications.provider(id))
  },

  async createProvider(data: {
    name: string
    providerType: string
    config: Record<string, unknown>
    isEnabled?: boolean
  }): Promise<NotificationProvider> {
    return api.post<NotificationProvider>(apiEndpoints.notifications.providers, data)
  },

  async updateProvider(
    id: string,
    data: {
      name?: string
      isEnabled?: boolean
      config?: Record<string, unknown>
    }
  ): Promise<NotificationProvider> {
    return api.patch<NotificationProvider>(apiEndpoints.notifications.provider(id), data)
  },

  async deleteProvider(id: string): Promise<void> {
    await api.delete(apiEndpoints.notifications.provider(id))
  },

  async testProvider(id: string): Promise<NotificationTestResult> {
    return api.post<NotificationTestResult>(apiEndpoints.notifications.testProvider(id))
  },

  async getProviderTypes(): Promise<NotificationProviderTypeInfo[]> {
    const response = await api.get<{ providerTypes: NotificationProviderTypeInfo[] }>(
      apiEndpoints.notifications.providerTypes
    )
    return response.providerTypes
  },

  async getPushbulletDevices(accessToken: string): Promise<PushbulletDevice[]> {
    const response = await api.get<{ devices: PushbulletDevice[] }>(
      apiEndpoints.notifications.pushbulletDevices,
      { accessToken }
    )
    return response.devices
  },

  async getPushbulletDevicesByProvider(providerId: string): Promise<PushbulletDevice[]> {
    const response = await api.get<{ devices: PushbulletDevice[] }>(
      apiEndpoints.notifications.pushbulletDevices,
      { providerId }
    )
    return response.devices
  },
}

export default notificationsService

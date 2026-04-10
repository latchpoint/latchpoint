import api from './api'
import { apiEndpoints } from './endpoints'
import type {
  NotificationProvider,
  NotificationProviderTypeInfo,
  NotificationTestResult,
  PushbulletDevice,
} from '@/types/notifications'

export const notificationsService = {
  // Provider read-only operations
  async listProviders(): Promise<NotificationProvider[]> {
    // Backend returns a plain array, not paginated response
    return api.get<NotificationProvider[]>(apiEndpoints.notifications.providers)
  },

  async getProvider(id: string): Promise<NotificationProvider> {
    return api.get<NotificationProvider>(apiEndpoints.notifications.provider(id))
  },

  async testProvider(id: string): Promise<NotificationTestResult> {
    return api.post<NotificationTestResult>(apiEndpoints.notifications.testProvider(id))
  },

  async toggleProvider(id: string, isEnabled: boolean): Promise<NotificationProvider> {
    return api.patch<NotificationProvider>(apiEndpoints.notifications.provider(id), { is_enabled: isEnabled })
  },

  // Provider types metadata
  async getProviderTypes(): Promise<NotificationProviderTypeInfo[]> {
    const response = await api.get<{ providerTypes: NotificationProviderTypeInfo[] }>(
      apiEndpoints.notifications.providerTypes
    )
    return response.providerTypes
  },

  // Pushbullet-specific endpoints
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

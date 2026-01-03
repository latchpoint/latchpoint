import api from './api'
import { apiEndpoints } from './endpoints'
import type {
  NotificationProvider,
  NotificationProviderCreate,
  NotificationProviderUpdate,
  NotificationProviderTypeInfo,
  NotificationTestResult,
  PushbulletDevice,
  PushbulletTokenValidation,
} from '@/types/notifications'

export const notificationsService = {
  // Provider CRUD
  async listProviders(): Promise<NotificationProvider[]> {
    // Backend returns a plain array, not paginated response
    return api.get<NotificationProvider[]>(apiEndpoints.notifications.providers)
  },

  async getProvider(id: string): Promise<NotificationProvider> {
    return api.get<NotificationProvider>(apiEndpoints.notifications.provider(id))
  },

  async createProvider(data: NotificationProviderCreate): Promise<NotificationProvider> {
    return api.post<NotificationProvider>(apiEndpoints.notifications.providers, data)
  },

  async updateProvider(id: string, data: NotificationProviderUpdate): Promise<NotificationProvider> {
    return api.patch<NotificationProvider>(apiEndpoints.notifications.provider(id), data)
  },

  async deleteProvider(id: string): Promise<void> {
    return api.delete(apiEndpoints.notifications.provider(id))
  },

  async testProvider(id: string): Promise<NotificationTestResult> {
    return api.post<NotificationTestResult>(apiEndpoints.notifications.testProvider(id))
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

  async validatePushbulletToken(accessToken: string): Promise<PushbulletTokenValidation> {
    return api.post<PushbulletTokenValidation>(
      apiEndpoints.notifications.pushbulletValidateToken,
      { accessToken }
    )
  },
}

export default notificationsService

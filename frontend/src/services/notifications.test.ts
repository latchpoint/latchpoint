import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { notificationsService } from './notifications'

describe('notifications', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
    apiMock.delete.mockReset()
  })

  it('lists providers', async () => {
    apiMock.get.mockResolvedValue([{ id: 'p1' }])
    await notificationsService.listProviders()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.notifications.providers)
  })

  it('returns provider types from response wrapper', async () => {
    apiMock.get.mockResolvedValue({ providerTypes: [{ type: 'pushbullet' }] })
    const types = await notificationsService.getProviderTypes()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.notifications.providerTypes)
    expect(types).toEqual([{ type: 'pushbullet' }])
  })

  it('fetches pushbullet devices by provider id', async () => {
    apiMock.get.mockResolvedValue({ devices: [{ iden: 'd1' }] })
    const devices = await notificationsService.getPushbulletDevicesByProvider('p1')
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.notifications.pushbulletDevices, {
      providerId: 'p1',
    })
    expect(devices).toEqual([{ iden: 'd1' }])
  })

  it('validates pushbullet token via POST', async () => {
    apiMock.post.mockResolvedValue({ valid: true })
    await notificationsService.validatePushbulletToken('o.token')
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.notifications.pushbulletValidateToken, {
      accessToken: 'o.token',
    })
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { mqttService } from './mqtt'

describe('mqtt', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
  })

  it('gets status', async () => {
    apiMock.get.mockResolvedValue({ enabled: true, connected: false })
    await mqttService.getStatus()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.mqtt.status)
  })

  it('updates settings via PATCH', async () => {
    apiMock.patch.mockResolvedValue({ enabled: true })
    await mqttService.updateSettings({ enabled: true } as any)
    expect(apiMock.patch).toHaveBeenCalledWith(apiEndpoints.mqtt.settings, { enabled: true })
  })

  it('tests connection via POST', async () => {
    apiMock.post.mockResolvedValue({ ok: true })
    await mqttService.testConnection({ host: 'h', port: 1883 } as any)
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.mqtt.test, { host: 'h', port: 1883 })
  })
})

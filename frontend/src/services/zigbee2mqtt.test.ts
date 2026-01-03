import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { zigbee2mqttService } from './zigbee2mqtt'

describe('zigbee2mqtt', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
  })

  it('lists devices', async () => {
    apiMock.get.mockResolvedValue([])
    await zigbee2mqttService.listDevices()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.integrations.zigbee2mqtt.devices)
  })

  it('syncs devices via POST {}', async () => {
    apiMock.post.mockResolvedValue({ ok: true })
    await zigbee2mqttService.syncDevices()
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.integrations.zigbee2mqtt.syncDevices, {})
  })
})

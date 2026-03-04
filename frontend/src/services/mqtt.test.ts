import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { mqttService } from './mqtt'

describe('mqtt', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
  })

  it('gets status', async () => {
    apiMock.get.mockResolvedValue({ enabled: true, connected: false })
    await mqttService.getStatus()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.mqtt.status)
  })
})

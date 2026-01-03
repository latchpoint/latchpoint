import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { integrationsService } from './integrations'

describe('integrations', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
  })

  it('publishes HA MQTT alarm entity discovery via POST {}', async () => {
    apiMock.post.mockResolvedValue({ ok: true })
    await integrationsService.homeAssistantMqttAlarmEntity.publishDiscovery()
    expect(apiMock.post).toHaveBeenCalledWith(
      apiEndpoints.integrations.homeAssistantMqttAlarmEntity.publishDiscovery,
      {}
    )
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
  getData: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { homeAssistantService } from './homeAssistant'

describe('homeAssistant', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.patch.mockReset()
    apiMock.getData.mockReset()
  })

  it('gets status', async () => {
    apiMock.get.mockResolvedValue({ configured: false, reachable: false })
    await homeAssistantService.getStatus()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.homeAssistant.status)
  })

  it('updates settings via PATCH', async () => {
    apiMock.patch.mockResolvedValue({ enabled: true })
    await homeAssistantService.updateSettings({ enabled: true })
    expect(apiMock.patch).toHaveBeenCalledWith(apiEndpoints.homeAssistant.settings, { enabled: true })
  })

  it('lists entities via getData', async () => {
    apiMock.getData.mockResolvedValue([])
    await homeAssistantService.listEntities()
    expect(apiMock.getData).toHaveBeenCalledWith(apiEndpoints.homeAssistant.entities)
  })
})

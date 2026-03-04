import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  getData: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { homeAssistantService } from './homeAssistant'

describe('homeAssistant', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.getData.mockReset()
  })

  it('gets status', async () => {
    apiMock.get.mockResolvedValue({ configured: false, reachable: false })
    await homeAssistantService.getStatus()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.homeAssistant.status)
  })

  it('lists entities via getData', async () => {
    apiMock.getData.mockResolvedValue([])
    await homeAssistantService.listEntities()
    expect(apiMock.getData).toHaveBeenCalledWith(apiEndpoints.homeAssistant.entities)
  })
})

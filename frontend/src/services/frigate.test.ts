import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { frigateService } from './frigate'

describe('frigate', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.patch.mockReset()
  })

  it('lists detections with params', async () => {
    apiMock.get.mockResolvedValue([])
    await frigateService.listDetections({ limit: 5 })
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.integrations.frigate.detections, { limit: 5 })
  })

  it('gets options', async () => {
    apiMock.get.mockResolvedValue({ cameras: [] })
    await frigateService.getOptions()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.integrations.frigate.options)
  })
})

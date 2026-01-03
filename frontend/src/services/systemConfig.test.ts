import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { systemConfigService } from './systemConfig'

describe('systemConfig', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.patch.mockReset()
  })

  it('lists system config rows', async () => {
    apiMock.get.mockResolvedValue([])
    await systemConfigService.list()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.systemConfig.all)
  })

  it('updates a system config key via PATCH', async () => {
    apiMock.patch.mockResolvedValue({ key: 'k', value: 'v' })
    await systemConfigService.update('k', { value: 'v' })
    expect(apiMock.patch).toHaveBeenCalledWith(apiEndpoints.systemConfig.key('k'), { value: 'v' })
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  getPaginated: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { codesService } from './codes'

describe('codes', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
    apiMock.delete.mockReset()
    apiMock.getPaginated.mockReset()
  })

  it('lists codes with optional userId param', async () => {
    apiMock.get.mockResolvedValue([])
    await codesService.getCodes({ userId: 'u1' })
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.codes.all, { userId: 'u1' })
  })

  it('fetches code usage via paginated helper', async () => {
    apiMock.getPaginated.mockResolvedValue({ data: [], total: 0 })
    await codesService.getCodeUsage(1, { page: 2, pageSize: 10 } as any)
    expect(apiMock.getPaginated).toHaveBeenCalledWith(apiEndpoints.codes.usage(1), { page: 2, pageSize: 10 })
  })

  it('deactivates code via PATCH', async () => {
    apiMock.patch.mockResolvedValue({ id: 1, isActive: false })
    await codesService.deactivateCode(1)
    expect(apiMock.patch).toHaveBeenCalledWith(apiEndpoints.codes.detail(1), { isActive: false })
  })
})

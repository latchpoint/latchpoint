import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { doorCodesService } from './doorCodes'

describe('doorCodes', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
    apiMock.delete.mockReset()
  })

  it('lists door codes', async () => {
    apiMock.get.mockResolvedValue([])
    await doorCodesService.getDoorCodes({ userId: 'u1' })
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.doorCodes.all, { userId: 'u1' })
  })

  it('deletes door code with reauth password body', async () => {
    apiMock.delete.mockResolvedValue(undefined)
    await doorCodesService.deleteDoorCode(2, { reauthPassword: 'pw' })
    expect(apiMock.delete).toHaveBeenCalledWith(apiEndpoints.doorCodes.detail(2), { reauthPassword: 'pw' })
  })
})

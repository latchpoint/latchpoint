import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { controlPanelsService } from './controlPanels'

describe('controlPanels', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
    apiMock.delete.mockReset()
  })

  it('lists panels', async () => {
    apiMock.get.mockResolvedValue([])
    await controlPanelsService.list()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.controlPanels.all)
  })

  it('tests a panel via POST {}', async () => {
    apiMock.post.mockResolvedValue({ ok: true })
    await controlPanelsService.test(1)
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.controlPanels.test(1), {})
  })
})

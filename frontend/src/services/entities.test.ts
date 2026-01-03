import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { entitiesService } from './entities'

describe('entities', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
  })

  it('lists entities', async () => {
    apiMock.get.mockResolvedValue([])
    await entitiesService.list()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.entities.all)
  })

  it('syncs entities via POST {}', async () => {
    apiMock.post.mockResolvedValue({ imported: 1, updated: 0, timestamp: 't' })
    await entitiesService.sync()
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.entities.sync, {})
  })
})

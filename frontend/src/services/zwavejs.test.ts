import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { zwavejsService } from './zwavejs'

describe('zwavejs', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
  })

  it('gets nodes', async () => {
    apiMock.get.mockResolvedValue({ homeId: null, nodes: [] })
    await zwavejsService.getNodes()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.integrations.zwavejs.nodes)
  })

  it('syncs entities via POST {}', async () => {
    apiMock.post.mockResolvedValue({ imported: 0, updated: 0, timestamp: 't' })
    await zwavejsService.syncEntities()
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.integrations.zwavejs.syncEntities, {})
  })
})

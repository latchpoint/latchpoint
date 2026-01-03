import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { rulesService } from './rules'

describe('rules', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    apiMock.patch.mockReset()
    apiMock.delete.mockReset()
  })

  it('lists rules with params', async () => {
    apiMock.get.mockResolvedValue([])
    await rulesService.list({ kind: 'trigger' as any, enabled: true })
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.rules.all, { kind: 'trigger', enabled: true })
  })

  it('runs rules', async () => {
    apiMock.post.mockResolvedValue({ matched: 0 })
    await rulesService.run()
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.rules.run, {})
  })

  it('simulates rules with payload', async () => {
    apiMock.post.mockResolvedValue({ matchedRules: [] })
    await rulesService.simulate({ entities: [] } as any)
    expect(apiMock.post).toHaveBeenCalledWith(apiEndpoints.rules.simulate, { entities: [] })
  })

  it('deletes rule by id', async () => {
    apiMock.delete.mockResolvedValue(undefined)
    await rulesService.delete(12)
    expect(apiMock.delete).toHaveBeenCalledWith(apiEndpoints.rules.detail(12))
  })
})

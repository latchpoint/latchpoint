import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiEndpoints } from './endpoints'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
}))

vi.mock('./api', () => ({ default: apiMock, api: apiMock }))

import { usersService } from './users'

describe('users', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
  })

  it('lists users', async () => {
    apiMock.get.mockResolvedValue([])
    await usersService.listUsers()
    expect(apiMock.get).toHaveBeenCalledWith(apiEndpoints.users.all)
  })
})
